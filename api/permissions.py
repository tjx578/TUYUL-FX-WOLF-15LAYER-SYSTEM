"""
Dashboard Permissions
Allows POST for dashboard write routes, GET for read routes.
"""


class DashboardPermission:
    @staticmethod
    def allow(method: str, path: str = "") -> bool:
        """
        Check if method is allowed for given path.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path

        Returns:
            True if allowed, False otherwise
        """
        method = method.upper()

        # Allow POST for dashboard write routes
        if method == "POST" and "/api/v1/dashboard" in path:
            return True

        # Allow GET for all routes
        if method == "GET":
            return True

        # Deny all other methods
        return False


# Maintain backward compatibility alias
ReadOnlyPermission = DashboardPermission
# Placeholder
