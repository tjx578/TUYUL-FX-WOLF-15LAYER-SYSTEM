"""
Dashboard Permissions
READ-ONLY ENFORCEMENT
"""


class ReadOnlyPermission:
    @staticmethod
    def allow(method: str) -> bool:
        # Only allow GET
        return method.upper() == "GET"
# Placeholder
