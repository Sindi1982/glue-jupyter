import json
from functools import partial
import traitlets
from collections import defaultdict
from traitlets.utils.bunch import Bunch
from glue.core.state_objects import State
from glue.core import Data, Subset, ComponentID
from glue.external.echo import CallbackList
from matplotlib.colors import Colormap


MAGIC_IGNORE = '611cfa3b-ebb5-42d2-b5c7-ba9bce8b51a4'


def state_to_dict(state):

    # NOTE: we don't use state.as_dict since we need to treat lists
    # of states slightly differently.

    changes = {}
    for name in dir(state):
        if not name.startswith('_') and state.is_callback_property(name):
            item = getattr(state, name)
            if isinstance(item, CallbackList):
                item = {index: state_to_dict(value) if isinstance(value, State) else value
                        for index, value in enumerate(item)}
            changes[name] = item
    return changes


def update_state_from_dict(state, changes):

    if len(changes) == 0:
        return

    groups = defaultdict(list)
    for name in changes:
        if state.is_callback_property(name):
            groups[state._update_priority(name)].append(name)

    for priority in sorted(groups, reverse=True):
        for name in groups[priority]:
            if isinstance(getattr(state, name), CallbackList):
                callback_list = getattr(state, name)
                for i in range(len(callback_list)):
                    if i in changes[name]:
                        if isinstance(callback_list[i], State):
                            callback_list[i].update_from_dict(changes[name][i])
                        else:
                            callback_list[i] = changes[name][i]
            else:
                if changes[name] != MAGIC_IGNORE:
                    setattr(state, name, changes[name])


class GlueStateJSONEncoder(json.JSONEncoder):

    # Custom JSON encoder class that understands glue-specific objects, and
    # is used below in convert_state_to_json.

    def default(self, obj):
        if isinstance(obj, State):
            return state_to_dict(obj)
        elif isinstance(obj, (Data, Subset, ComponentID)):
            return MAGIC_IGNORE
        elif isinstance(obj, Colormap):
            return obj.name
        return json.JSONEncoder.default(self, obj)


class GlueState(traitlets.Any):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tag(to_json=self.convert_state_to_json,
                 from_json=self.update_state_from_json)

    def validate(self, obj, value):

        if value is None or isinstance(value, State):
            return value
        else:
            raise traitlets.TraitError('value should be a glue State instance')

    # When state objects change internally, the instance itself does not change
    # so we need to manually look for changes in the state and then manually
    # trigger a notification, which we do in the following two methods.

    def set(self, obj, state):
        super().set(obj, state)
        state.add_global_callback(partial(self.on_state_change, obj=obj))

    def on_state_change(self, *args, obj=None, **kwargs):
        obj.notify_change(Bunch({'name': self.name,
                                 'type': 'change',
                                 'value': self.get(obj),
                                 'new': self.get(obj)}))

    # NOTE: the following two methods are implemented as methods on the trait
    # because we need update_state_from_json to have an unambiguous reference
    # to the correct state instance. This means that overwriting these means
    # inheriting from GlueState rather than overwriting the tag.

    def convert_state_to_json(self, state, widget):
        if state is None:
            return {}
        else:
            return json.loads(json.dumps(state_to_dict(state), cls=GlueStateJSONEncoder))

    def update_state_from_json(self, json, widget):
        state = getattr(widget, self.name)
        update_state_from_dict(state, json)
        return state
