import sys
import os
import json
import imp
import inspect
import collections

command = sys.argv[1]
in_file = sys.argv[2]
out_file = sys.argv[3]

with open(in_file) as f:
    in_data = json.load(f)
    config = in_data['config']

# fake digdag_env module already imported
digdag_env_mod = sys.modules['digdag_env'] = imp.new_module('digdag_env')
digdag_env_mod.config = config
digdag_env_mod.subtask_config = collections.OrderedDict()
digdag_env_mod.state_params = {}
digdag_env_mod.export_params = {}
import digdag_env

# fake digdag module already imported
digdag_mod = sys.modules['digdag'] = imp.new_module('digdag')

class Env(object):
    def __init__(self, digdag_env_mod):
        self.config = digdag_env_mod.config
        self.subtask_config = digdag_env_mod.subtask_config
        self.state_params = digdag_env_mod.state_params
        self.export_params = digdag_env_mod.export_params
        self.subtask_index = 0

    def set_state(self, key, value):
        self.state_params[key] = value

    def export(self, key, value):
        self.export_params[key] = value

    def export_children(self, key, value):
        if "export" not in self.subtask_config:
            self.subtask_config["export"] = {}
        return self.subtask_config["export"]

    def add_subtask(self, function=None, **params):
        if function is not None and not isinstance(function, dict):
            if hasattr(function, "im_class"):
                # Python 2
                command = ".".join([function.im_class.__module__, function.im_class.__name__, function.__name__])
            else:
                # Python 3
                command = ".".join([function.__module__, function.__name__])
            config = params
            config["py>"] = command
        else:
            if isinstance(function, dict):
                config = function.copy()
                config.update(params)
            else:
                config = params
        try:
            json.dumps(config)
        except Exception as error:
            raise TypeError("Parameters must be serializable using JSON: %s" % str(error))
        self.subtask_config["+subtask" + str(self.subtask_index)] = config
        self.subtask_index += 1

digdag_mod.env = Env(digdag_env_mod)
import digdag

# add the archive path to improt path
sys.path.append(os.path.abspath(os.getcwd()))

def digdag_inspect_command(command):
    # package.name.Class.method
    fragments = command.split(".")
    method_name = fragments.pop()
    class_type = None
    callable_type = None
    try:
        mod = __import__(".".join(fragments), fromlist=[method_name])
        try:
            callable_type = getattr(mod, method_name)
        except AttributeError as error:
            raise AttributeError("Module '%s' has no attribute '%s'" % (".".join(fragments), method_name))
    except ImportError as error:
        class_name = fragments.pop()
        mod = __import__(".".join(fragments), fromlist=[class_name])
        try:
            class_type = getattr(mod, class_name)
        except AttributeError as error:
            raise AttributeError("Module '%s' has no attribute '%s'" % (".".join(fragments), method_name))

    if type(callable_type) == type:
        class_type = callable_type
        method_name = "run"

    if class_type is not None:
        return (class_type, method_name)
    else:
        return (callable_type, None)

def digdag_inspect_arguments(callable_type, exclude_self, config):
    if callable_type == object.__init__:
        # object.__init__ accepts *varargs and **keywords but it throws exception
        return {}
    spec = inspect.getargspec(callable_type)
    args = {}
    for idx, key in enumerate(spec.args):
        if exclude_self and idx == 0:
            continue
        if key in config:
            args[key] = config[key]
        else:
            if spec.defaults is None or len(spec.defaults) < idx:
                # this keyword is required but not in config. raising an error.
                if hasattr(callable_type, '__qualname__'):
                    # Python 3
                    name = callable_type.__qualname__
                elif hasattr(callable_type, 'im_class'):
                    # Python 2
                    name = "%s.%s" % (callable_type.im_class.__name__, callable_type.__name__)
                else:
                    name = callable_type.__name__
                raise TypeError("Method '%s' requires parameter '%s' but not set" % (name, key))
    if spec.keywords:
        # above code was only for validation
        return config
    else:
        return args

callable_type, method_name = digdag_inspect_command(command)

if method_name:
    init_args = digdag_inspect_arguments(callable_type.__init__, True, config)
    instance = callable_type(**init_args)

    method = getattr(instance, method_name)
    method_args = digdag_inspect_arguments(method, True, config)
    result = method(**method_args)

else:
    args = digdag_inspect_arguments(callable_type, False, config)
    result = callable_type(**args)

out = {
    'subtask_config': digdag_env.subtask_config,
    'export_params': digdag_env.export_params,
    'state_params': digdag_env.state_params,
}

with open(out_file, 'w') as f:
    json.dump(out, f)

