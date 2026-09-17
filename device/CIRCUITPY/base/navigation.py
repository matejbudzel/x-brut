"""Small in-memory navigation history shared by base and project routes."""


class Navigation:
    """A route stack; route state is intentionally small and reboot-local."""
    def __init__(self, home_route):
        self._home = home_route
        self._entries = [{"route": home_route, "state": {}}]

    @property
    def route(self):
        return self._entries[-1]["route"]

    @property
    def state(self):
        return self._entries[-1]["state"]

    @property
    def can_back(self):
        return len(self._entries) > 1

    def push(self, route, state=None):
        self._entries.append({"route": route, "state": state or {}})
        return self._entries[-1]

    def replace(self, route, state=None):
        self._entries[-1] = {"route": route, "state": state or {}}
        return self._entries[-1]

    def update(self, **state):
        self.state.update(state)

    def back(self):
        if not self.can_back:
            return None
        self._entries.pop()
        return self._entries[-1]

    def home(self):
        self._entries[:] = [{"route": self._home, "state": {}}]
        return self._entries[-1]
