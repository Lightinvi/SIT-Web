"""Once-per-system-local-day rewards recorded atomically with the shard ledger."""
from datetime import datetime, timedelta
import secrets
import time

from app.models.star_shard import append_entry, ensure_schema as ensure_ledger
from app.models.record_ids import create_record_table, new_record_id

BASE_REWARD = 10
PRIZES = (
    {'multiplier': 0.5, 'probability': 8, 'reward': 5},
    {'multiplier': 1, 'probability': 65, 'reward': 10},
    {'multiplier': 2, 'probability': 12, 'reward': 20},
    {'multiplier': 2.5, 'probability': 11, 'reward': 25},
    {'multiplier': 5, 'probability': 4, 'reward': 50},
)


def day_window(now):
    """Use the process's system timezone, including DST at the next local midnight."""
    local = datetime.fromtimestamp(now)
    # Resolve each local midnight independently; DST days need not be 24 hours.
    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time())
    return local.date().isoformat(), midnight.timestamp()


def ensure_schema(tx):
    """Create immutable spin receipts with daily and retry uniqueness constraints."""
    ensure_ledger(tx)
    create_record_table(tx, 'daily_spinner')


def choose_prize():
    """Map 100 cryptographically random integer outcomes onto the published weights."""
    roll = secrets.randbelow(100)
    cumulative = 0
    for prize in PRIZES:
        cumulative += prize['probability']
        if roll < cumulative:
            return prize
    raise RuntimeError('Invalid spinner probability configuration')


def public_state(now):
    """Expose the exact reward odds and server-owned daily reset boundary."""
    day, reset = day_window(now)
    return {'day': day, 'nextResetAt': reset, 'serverTime': now,
            'timezone': time.strftime('%Z', time.localtime(now)),
            'baseReward': BASE_REWARD, 'prizes': list(PRIZES)}


def member_state(tx, user_id, now):
    """Return today's own receipt and eligibility without drawing or crediting anything."""
    state = public_state(now)
    rows = tx.select('daily_spinner', {'userId': user_id, 'spinDate': state['day']})
    return {**state, 'todaySpin': rows[0] if rows else None, 'canSpin': not rows}


def spin(db, user_id, request_id, *, now=None):
    """Serialize a daily draw and ledger credit, replaying retries even across midnight."""
    with db.transaction(immediate=True) as tx:
        ensure_schema(tx)
        timestamp = time.time() if now is None else now
        state = member_state(tx, user_id, timestamp)
        previous = tx.select('daily_spinner', {'userId': user_id, 'requestId': request_id})
        record = previous[0] if previous else state['todaySpin']
        if record:
            return {**state, 'result': record, 'awarded': False}
        prize = choose_prize()
        spin_id = new_record_id()
        tx.insert('daily_spinner', {
            'id': spin_id,
            'userId': user_id, 'spinDate': state['day'], 'requestId': request_id,
            'multiplier': prize['multiplier'], 'baseReward': BASE_REWARD,
            'reward': prize['reward'], 'createdAt': timestamp,
        })
        append_entry(tx, user_id, prize['reward'], 'daily_spinner', str(spin_id),
                     f"每日轉盤 {prize['multiplier']:g}x 獎勵")
        record = tx.select('daily_spinner', {'id': spin_id})[0]
        return {**state, 'canSpin': False, 'todaySpin': record, 'result': record, 'awarded': True}
