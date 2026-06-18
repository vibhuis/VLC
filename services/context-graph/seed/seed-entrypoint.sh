#!/bin/bash
# Start Neo4j, wait for it to accept bolt, run the seed once (idempotent via a marker
# node), then hand the foreground back to Neo4j so the container stays healthy. [spec §5.2]
set -euo pipefail

PASSWORD="${NEO4J_AUTH##*/}"
MARKER='MATCH (m:VclSeedMarker) RETURN count(m) AS c'

seed() {
  # Wait for bolt to come up.
  for _ in $(seq 1 60); do
    if cypher-shell -u neo4j -p "$PASSWORD" "RETURN 1" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  already=$(cypher-shell -u neo4j -p "$PASSWORD" --format plain "$MARKER" 2>/dev/null | tail -n1 || echo 0)
  if [ "${already:-0}" != "0" ]; then
    echo "[vcl-seed] graph already seeded; skipping."
    return 0
  fi

  echo "[vcl-seed] loading context graph..."
  cypher-shell -u neo4j -p "$PASSWORD" -f /seed/load.cypher
  cypher-shell -u neo4j -p "$PASSWORD" "CREATE (:VclSeedMarker {seeded_at: datetime()})"
  echo "[vcl-seed] seeding complete."
}

# Run the seeder in the background; Neo4j runs in the foreground (PID 1 child).
seed &

# Delegate to the stock Neo4j entrypoint.
exec /startup/docker-entrypoint.sh "$@"
