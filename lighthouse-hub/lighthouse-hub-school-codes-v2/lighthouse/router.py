import re


class Router:
    def __init__(self):
        self.routes = []  # list of (method, regex, param_names, handler, roles)

    def add(self, method, path, handler, roles=None):
        param_names = re.findall(r"<(\w+)>", path)
        pattern = re.sub(r"<(\w+)>", r"(?P<\1>[^/]+)", path)
        regex = re.compile("^" + pattern + "$")
        self.routes.append((method.upper(), regex, param_names, handler, roles))

    def get(self, path, roles=None):
        def deco(fn):
            self.add("GET", path, fn, roles)
            return fn
        return deco

    def post(self, path, roles=None):
        def deco(fn):
            self.add("POST", path, fn, roles)
            return fn
        return deco

    def patch(self, path, roles=None):
        def deco(fn):
            self.add("PATCH", path, fn, roles)
            return fn
        return deco

    def delete(self, path, roles=None):
        def deco(fn):
            self.add("DELETE", path, fn, roles)
            return fn
        return deco

    def match(self, method, path):
        for m, regex, param_names, handler, roles in self.routes:
            if m != method:
                continue
            mo = regex.match(path)
            if mo:
                return handler, mo.groupdict(), roles
        return None, None, None
