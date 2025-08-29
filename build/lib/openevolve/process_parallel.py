"""
Process-based parallel controller for true parallelism
(Fixed: in-worker diff sanitization, removed import-time side effects)
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import os
import time
from concurrent.futures import ProcessPoolExecutor, Future
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from openevolve.config import Config
from openevolve.database import Program, ProgramDatabase

logger = logging.getLogger(__name__)

# --- Patch-sanitizer import with safe fallback -------------------------------
try:
    # This will be monkey-patched by entrypoint to a stronger sanitizer.
    from openevolve.utils.patch_sanitizer import extract_raw_patch as _extract_raw_patch  # type: ignore
except Exception:  # pragma: no cover
    def _extract_raw_patch(text: str, **_: Any) -> str:
        return ""

def _sanitize_llm_patch(raw: str) -> str:
    """
    Normalize a model-produced patch/diff so the rest of the pipeline can apply it.
    - Retargets hallucinated paths to allowed targets (api.py/data_layer.py)
    - Accepts both old/new extract_raw_patch signatures
    """
    allowed_files = [
        p.strip() for p in os.getenv("OE_ALLOWED_FILES", "api.py,data_layer.py").split(",") if p.strip()
    ]
    default_target = os.getenv("OE_TARGET_FILE", "api.py")

    # Try new signature first, then fallback to legacy.
    try:
        patched = _extract_raw_patch(
            raw,
            allowed_targets=allowed_files,           # newer sanitizer supports these
            default_target=default_target,
        )
    except TypeError:
        patched = _extract_raw_patch(raw)

    return (patched or "").strip()

# --- Worker payloads ---------------------------------------------------------
@dataclass
class SerializableResult:
    """Result that can be pickled and sent between processes"""
    child_program_dict: Optional[Dict[str, Any]] = None
    parent_id: Optional[str] = None
    iteration_time: float = 0.0
    prompt: Optional[Dict[str, str]] = None
    llm_response: Optional[str] = None
    artifacts: Optional[Dict[str, Any]] = None
    iteration: int = 0
    error: Optional[str] = None


def _worker_init(config_dict: dict, evaluation_file: str) -> None:
    """Initialize worker process with necessary components"""
    global _worker_config, _worker_evaluation_file, _worker_evaluator, _worker_llm_ensemble, _worker_prompt_sampler

    from openevolve.config import (
        Config, DatabaseConfig, EvaluatorConfig, LLMConfig, PromptConfig, LLMModelConfig
    )

    models = [LLMModelConfig(**m) for m in config_dict["llm"]["models"]]
    evaluator_models = [LLMModelConfig(**m) for m in config_dict["llm"]["evaluator_models"]]

    llm_dict = config_dict["llm"].copy()
    llm_dict["models"] = models
    llm_dict["evaluator_models"] = evaluator_models
    llm_config = LLMConfig(**llm_dict)

    prompt_config = PromptConfig(**config_dict["prompt"])
    database_config = DatabaseConfig(**config_dict["database"])
    evaluator_config = EvaluatorConfig(**config_dict["evaluator"])

    _worker_config = Config(
        llm=llm_config,
        prompt=prompt_config,
        database=database_config,
        evaluator=evaluator_config,
        **{k: v for k, v in config_dict.items() if k not in ["llm", "prompt", "database", "evaluator"]},
    )
    _worker_evaluation_file = evaluation_file
    _worker_evaluator = None
    _worker_llm_ensemble = None
    _worker_prompt_sampler = None


def _lazy_init_worker_components():
    """Lazily initialize expensive components on first use"""
    global _worker_evaluator, _worker_llm_ensemble, _worker_prompt_sampler

    if _worker_llm_ensemble is None:
        from openevolve.llm.ensemble import LLMEnsemble
        _worker_llm_ensemble = LLMEnsemble(_worker_config.llm.models)

    if _worker_prompt_sampler is None:
        from openevolve.prompt.sampler import PromptSampler
        _worker_prompt_sampler = PromptSampler(_worker_config.prompt)

    if _worker_evaluator is None:
        from openevolve.evaluator import Evaluator
        from openevolve.llm.ensemble import LLMEnsemble
        from openevolve.prompt.sampler import PromptSampler

        evaluator_llm = LLMEnsemble(_worker_config.llm.evaluator_models)
        evaluator_prompt = PromptSampler(_worker_config.prompt)
        evaluator_prompt.set_templates("evaluator_system_message")

        _worker_evaluator = Evaluator(
            _worker_config.evaluator,
            _worker_evaluation_file,
            evaluator_llm,
            evaluator_prompt,
            database=None,  # No shared DB in worker
        )


def _run_iteration_worker(
    iteration: int, db_snapshot: Dict[str, Any], parent_id: str, inspiration_ids: List[str]
) -> SerializableResult:
    """Run a single iteration in a worker process"""
    try:
        _lazy_init_worker_components()

        programs = {pid: Program(**prog_dict) for pid, prog_dict in db_snapshot["programs"].items()}
        parent = programs[parent_id]
        inspirations = [programs[pid] for pid in inspiration_ids if pid in programs]

        parent_artifacts = db_snapshot["artifacts"].get(parent_id)
        parent_island = parent.metadata.get("island", db_snapshot["current_island"])
        island_programs = [programs[pid] for pid in db_snapshot["islands"][parent_island] if pid in programs]

        from openevolve.utils.metrics_utils import safe_numeric_average
        island_programs.sort(
            key=lambda p: p.metrics.get("combined_score", safe_numeric_average(p.metrics)), reverse=True
        )

        programs_for_prompt = island_programs[: _worker_config.prompt.num_top_programs + _worker_config.prompt.num_diverse_programs]
        best_programs_only = island_programs[: _worker_config.prompt.num_top_programs]

        prompt = _worker_prompt_sampler.build_prompt(
            current_program=parent.code,
            parent_program=parent.code,
            program_metrics=parent.metrics,
            previous_programs=[p.to_dict() for p in best_programs_only],
            top_programs=[p.to_dict() for p in programs_for_prompt],
            inspirations=[p.to_dict() for p in inspirations],
            language=_worker_config.language,
            evolution_round=iteration,
            diff_based_evolution=_worker_config.diff_based_evolution,
            program_artifacts=parent_artifacts,
            feature_dimensions=db_snapshot.get("feature_dimensions", []),
        )

        t0 = time.time()

        # Generate diff or full rewrite
        llm_response = asyncio.run(
            _worker_llm_ensemble.generate_with_context(
                system_message=prompt["system"],
                messages=[{"role": "user", "content": prompt["user"]}],
            )
        )

        if _worker_config.diff_based_evolution:
            # --- sanitize inside worker (CRITICAL FIX) ---
            raw = (llm_response or "").strip()
            if raw.upper().startswith("SKIP"):
                return SerializableResult(error="Model skipped", iteration=iteration)

            sanitized = _sanitize_llm_patch(raw)
            if sanitized:
                llm_response = sanitized  # use sanitized diff
            else:
                # keep raw so the evaluator logs show the original content
                logger.warning("Sanitizer returned empty; proceeding with raw diff response")

            from openevolve.utils.code_utils import extract_diffs, apply_diff, format_diff_summary

            diff_blocks = extract_diffs(llm_response)
            if not diff_blocks:
                return SerializableResult(error="No valid diffs found in response", iteration=iteration)

            child_code = apply_diff(parent.code, llm_response)
            changes_summary = format_diff_summary(diff_blocks)

        else:
            from openevolve.utils.code_utils import parse_full_rewrite
            new_code = parse_full_rewrite(llm_response, _worker_config.language)
            if not new_code:
                return SerializableResult(error="No valid code found in response", iteration=iteration)
            child_code = new_code
            changes_summary = "Full rewrite"

        if len(child_code) > _worker_config.max_code_length:
            return SerializableResult(
                error=f"Generated code exceeds maximum length ({len(child_code)} > {_worker_config.max_code_length})",
                iteration=iteration,
            )

        import uuid
        child_id = str(uuid.uuid4())
        child_metrics = asyncio.run(_worker_evaluator.evaluate_program(child_code, child_id))
        artifacts = _worker_evaluator.get_pending_artifacts(child_id)

        child_program = Program(
            id=child_id,
            code=child_code,
            language=_worker_config.language,
            parent_id=parent.id,
            generation=parent.generation + 1,
            metrics=child_metrics,
            iteration_found=iteration,
            metadata={"changes": changes_summary, "parent_metrics": parent.metrics, "island": parent_island},
        )

        return SerializableResult(
            child_program_dict=child_program.to_dict(),
            parent_id=parent.id,
            iteration_time=time.time() - t0,
            prompt=prompt,
            llm_response=llm_response,
            artifacts=artifacts,
            iteration=iteration,
        )

    except Exception as e:  # pragma: no cover
        logger.exception(f"Error in worker iteration {iteration}")
        return SerializableResult(error=str(e), iteration=iteration)


class ProcessParallelController:
    """Controller for process-based parallel evolution"""

    def __init__(self, config: Config, evaluation_file: str, database: ProgramDatabase):
        self.config = config
        self.evaluation_file = evaluation_file
        self.database = database

        self.executor: Optional[ProcessPoolExecutor] = None
        self.shutdown_event = mp.Event()

        self.num_workers = config.evaluator.parallel_evaluations
        self.num_islands = config.database.num_islands
        self.worker_island_map: Dict[int, int] = {
            worker_id: (worker_id % self.num_islands) for worker_id in range(self.num_workers)
        }

        logger.info(f"Initialized process parallel controller with {self.num_workers} workers")
        logger.info(f"Worker-to-island mapping: {self.worker_island_map}")

    def _serialize_config(self, config: Config) -> dict:
        return {
            "llm": {
                "models": [asdict(m) for m in config.llm.models],
                "evaluator_models": [asdict(m) for m in config.llm.evaluator_models],
                "api_base": config.llm.api_base,
                "api_key": config.llm.api_key,
                "temperature": config.llm.temperature,
                "top_p": config.llm.top_p,
                "max_tokens": config.llm.max_tokens,
                "timeout": config.llm.timeout,
                "retries": config.llm.retries,
                "retry_delay": config.llm.retry_delay,
            },
            "prompt": asdict(config.prompt),
            "database": asdict(config.database),
            "evaluator": asdict(config.evaluator),
            "max_iterations": config.max_iterations,
            "checkpoint_interval": config.checkpoint_interval,
            "log_level": config.log_level,
            "log_dir": config.log_dir,
            "random_seed": config.random_seed,
            "diff_based_evolution": config.diff_based_evolution,
            "max_code_length": config.max_code_length,
            "language": config.language,
        }

    def start(self) -> None:
        config_dict = self._serialize_config(self.config)
        self.executor = ProcessPoolExecutor(
            max_workers=self.num_workers,
            initializer=_worker_init,
            initargs=(config_dict, self.evaluation_file),
        )
        logger.info(f"Started process pool with {self.num_workers} processes")

    def stop(self) -> None:
        self.shutdown_event.set()
        if self.executor:
            self.executor.shutdown(wait=True)
            self.executor = None
        logger.info("Stopped process pool")

    def request_shutdown(self) -> None:
        logger.info("Graceful shutdown requested...")
        self.shutdown_event.set()

    def _create_database_snapshot(self) -> Dict[str, Any]:
        snapshot = {
            "programs": {pid: prog.to_dict() for pid, prog in self.database.programs.items()},
            "islands": [list(island) for island in self.database.islands],
            "current_island": self.database.current_island,
            "feature_dimensions": self.database.config.feature_dimensions,
            "artifacts": {},
        }
        for pid in list(self.database.programs.keys())[:100]:
            artifacts = self.database.get_artifacts(pid)
            if artifacts:
                snapshot["artifacts"][pid] = artifacts
        return snapshot

    async def run_evolution(
        self,
        start_iteration: int,
        max_iterations: int,
        target_score: Optional[float] = None,
        checkpoint_callback=None,
    ):
        if not self.executor:
            raise RuntimeError("Process pool not started")

        total_iterations = start_iteration + max_iterations
        logger.info(
            f"Starting process-based evolution from iteration {start_iteration} for {max_iterations} iterations "
            f"(total: {total_iterations})"
        )

        pending_futures: Dict[int, Future] = {}
        island_pending: Dict[int, List[int]] = {i: [] for i in range(self.num_islands)}
        batch_size = min(self.num_workers * 2, max_iterations)

        batch_per_island = max(1, batch_size // self.num_islands) if batch_size > 0 else 0
        current_iteration = start_iteration

        for island_id in range(self.num_islands):
            for _ in range(batch_per_island):
                if current_iteration < total_iterations:
                    fut = self._submit_iteration(current_iteration, island_id)
                    if fut:
                        pending_futures[current_iteration] = fut
                        island_pending[island_id].append(current_iteration)
                    current_iteration += 1

        next_iteration = current_iteration
        completed_iterations = 0
        programs_per_island = max(1, max_iterations // (self.config.database.num_islands * 10))
        current_island_counter = 0

        while pending_futures and completed_iterations < max_iterations and not self.shutdown_event.is_set():
            completed_iteration = None
            for it, fut in list(pending_futures.items()):
                if fut.done():
                    completed_iteration = it
                    break

            if completed_iteration is None:
                await asyncio.sleep(0.01)
                continue

            fut = pending_futures.pop(completed_iteration)
            try:
                result = fut.result()
                if result.error:
                    logger.warning(f"Iteration {completed_iteration} error: {result.error}")
                elif result.child_program_dict:
                    child_program = Program(**result.child_program_dict)
                    self.database.add(child_program, iteration=completed_iteration)

                    if result.artifacts:
                        self.database.store_artifacts(child_program.id, result.artifacts)

                    if result.prompt:
                        self.database.log_prompt(
                            template_key=("full_rewrite_user" if not self.config.diff_based_evolution else "diff_user"),
                            program_id=child_program.id,
                            prompt=result.prompt,
                            responses=[result.llm_response] if result.llm_response else [],
                        )

                    if completed_iteration > start_iteration and current_island_counter >= programs_per_island:
                        self.database.next_island()
                        current_island_counter = 0
                        logger.debug(f"Switched to island {self.database.current_island}")

                    current_island_counter += 1
                    self.database.increment_island_generation()

                    if self.database.should_migrate():
                        logger.info(f"Performing migration at iteration {completed_iteration}")
                        self.database.migrate_programs()
                        self.database.log_island_status()

                    logger.info(
                        f"Iteration {completed_iteration}: Program {child_program.id} "
                        f"(parent: {result.parent_id}) completed in {result.iteration_time:.2f}s"
                    )

                    if child_program.metrics:
                        metrics_str = ", ".join(
                            f"{k}={v:.4f}" if isinstance(v, (int, float)) else f"{k}={v}"
                            for k, v in child_program.metrics.items()
                        )
                        logger.info(f"Metrics: {metrics_str}")

                        if not hasattr(self, "_warned_about_combined_score"):
                            self._warned_about_combined_score = False

                        if "combined_score" not in child_program.metrics and not self._warned_about_combined_score:
                            from openevolve.utils.metrics_utils import safe_numeric_average
                            avg_score = safe_numeric_average(child_program.metrics)
                            logger.warning(
                                "⚠️  No 'combined_score' metric found. Using average of numeric metrics "
                                f"({avg_score:.4f}) for guidance. Consider adding a proper combined_score."
                            )
                            self._warned_about_combined_score = True

                    if self.database.best_program_id == child_program.id:
                        logger.info(f"🌟 New best solution at iteration {completed_iteration}: {child_program.id}")

                    if completed_iteration > 0 and completed_iteration % self.config.checkpoint_interval == 0:
                        logger.info(f"Checkpoint interval reached at iteration {completed_iteration}")
                        self.database.log_island_status()
                        if checkpoint_callback:
                            checkpoint_callback(completed_iteration)

                    if target_score is not None and child_program.metrics:
                        numeric = [v for v in child_program.metrics.values() if isinstance(v, (int, float))]
                        if numeric and (sum(numeric) / len(numeric)) >= target_score:
                            logger.info(f"Target score {target_score} reached at iteration {completed_iteration}")
                            break

            except Exception as e:  # pragma: no cover
                logger.error(f"Error processing result from iteration {completed_iteration}: {e}")

            completed_iterations += 1

            for island_id, lst in island_pending.items():
                if completed_iteration in lst:
                    lst.remove(completed_iteration)
                    break

            for island_id in range(self.num_islands):
                if len(island_pending[island_id]) < batch_per_island and next_iteration < total_iterations and not self.shutdown_event.is_set():
                    fut2 = self._submit_iteration(next_iteration, island_id)
                    if fut2:
                        pending_futures[next_iteration] = fut2
                        island_pending[island_id].append(next_iteration)
                        next_iteration += 1
                        break

        if self.shutdown_event.is_set():
            logger.info("Shutdown requested, canceling remaining evaluations…")
            for fut in pending_futures.values():
                fut.cancel()

        logger.info("Evolution completed")
        return self.database.get_best_program()

    def _submit_iteration(self, iteration: int, island_id: Optional[int] = None) -> Optional[Future]:
        try:
            target_island = island_id if island_id is not None else self.database.current_island
            original_island = self.database.current_island
            self.database.current_island = target_island
            try:
                parent, inspirations = self.database.sample(num_inspirations=self.config.prompt.num_top_programs)
            finally:
                self.database.current_island = original_island

            db_snapshot = self._create_database_snapshot()
            db_snapshot["sampling_island"] = target_island

            return self.executor.submit(
                _run_iteration_worker, iteration, db_snapshot, parent.id, [insp.id for insp in inspirations]
            )
        except Exception as e:  # pragma: no cover
            logger.error(f"Error submitting iteration {iteration}: {e}")
            return None