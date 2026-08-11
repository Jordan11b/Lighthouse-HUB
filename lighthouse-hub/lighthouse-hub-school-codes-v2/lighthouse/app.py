from .router import Router
from . import routes_auth, routes_people, routes_schedule, routes_attendance
from . import routes_makeups, routes_approvals, routes_dashboard, routes_misc, routes_alerts, routes_import

main_router = Router()

for mod in (routes_auth, routes_people, routes_schedule, routes_attendance,
            routes_makeups, routes_approvals, routes_dashboard, routes_misc, routes_alerts, routes_import):
    main_router.routes.extend(mod.router.routes)
