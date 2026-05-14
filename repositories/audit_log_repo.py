from models.audit_log import AuditLog


class AuditLogRepository:
    @staticmethod
    async def create(audit_log: AuditLog) -> AuditLog:
        return await audit_log.insert()
