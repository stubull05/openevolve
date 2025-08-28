# sitecustomize.py — auto-loaded if its folder is on sys.path.
# Makes TemplateManager accept both 'custom_template_dir' and 'template_dir'.
import importlib, inspect

def _patch(mod_name):
    try:
        m = importlib.import_module(mod_name)
        TM = m.TemplateManager
        sig = inspect.signature(TM.__init__)
        if "custom_template_dir" not in sig.parameters:
            orig = TM.__init__
            def __init__(self, *args, **kwargs):
                if "custom_template_dir" in kwargs and "template_dir" not in kwargs and not args:
                    kwargs["template_dir"] = kwargs.pop("custom_template_dir")
                return orig(self, *args, **kwargs)
            TM.__init__ = __init__
    except Exception:
        pass

for name in ("openevolve.prompt.templates", "openevolve.prompt.template_manager"):
    _patch(name)