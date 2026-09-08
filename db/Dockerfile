FROM postgres:17-alpine

# Baked in rather than bind mounted. A mounted host path is not visible inside every Docker VM, and
# when it is missing the mount lands as an empty directory and the migration silently applies nothing.
COPY migrations /migrations
COPY migrate.sh /migrate.sh

ENTRYPOINT ["sh", "/migrate.sh"]
