"""Read-only GeoSmart AUTO-REROUTE simulation for a connected clinic network.

All times, driving times and branches here are fictional. This module NEVER reads
or modifies PostgreSQL and never calls Google Maps. Production cross-branch
moves require tenant-level opt-in, actual traffic data, verified qualifications
and an atomic double-booking-safe transfer.
"""
from datetime import datetime, timedelta

NOW = 9 * 60 + 35
ORIGINAL = 10 * 60
SERVICE_DURATION = 30
BUFFER = 5
GRACE = 10


def fmt(minutes: int) -> str:
    return (datetime(2026, 10, 13) + timedelta(minutes=minutes)).strftime('%H:%M')


def simulate_geo_reroute(scenario: str, traffic_delay_minutes: int,
                         max_delay_minutes: int, auto_reroute_opt_in: bool) -> dict:
    """Select earliest feasible completion, breaking ties by driving ETA.

    The demo's fictional branches represent ONE clinic network. An independent
    clinic, unqualified professional or occupied slot is never eligible.
    """
    central_eta = 15 + traffic_delay_minutes
    east_eta = 9 + (traffic_delay_minutes * 1 // 5)
    south_eta = 12 + (traffic_delay_minutes * 3 // 10)
    arrival_central = NOW + central_eta
    on_time = arrival_central <= ORIGINAL + GRACE

    branches = [
        {"branch": "Northstar Central", "branch_id": "central", "organization": "Northstar Family Clinics",
         "service": "Initial consultation", "staff": "Dr Nisha Kapoor", "travel_minutes": central_eta,
         "slots": [ORIGINAL + 30] if scenario != 'fully_booked' else [], "qualified": True,
         "note": "Original branch; same service and assigned doctor"},
        {"branch": "Northstar East", "branch_id": "east", "organization": "Northstar Family Clinics",
         "service": "Initial consultation", "staff": "Dr Kavya Rao", "travel_minutes": east_eta,
         "slots": [] if scenario in ('fully_booked', 'nearest_full') else [ORIGINAL],
         "qualified": scenario != 'nearest_unqualified',
         "note": "Clinic network branch with same service"},
        {"branch": "Northstar South", "branch_id": "south", "organization": "Northstar Family Clinics",
         "service": "Initial consultation", "staff": "Dr Aman Shah", "travel_minutes": south_eta,
         "slots": [] if scenario == 'fully_booked' else [ORIGINAL + 15],
         "qualified": True, "note": "Clinic network branch with same service"},
    ]
    # Model other confirmed patients only to demonstrate non-displacement.
    people = [
        {"customer": "Rahul", "role": "Late customer / auto-reroute enrolled", "branch": "Northstar Central",
         "time": fmt(ORIGINAL), "original_time": fmt(ORIGINAL), "status": "confirmed", "kind": "owner"},
        {"customer": "Priya", "role": "Existing confirmed patient", "branch": "Northstar Central",
         "time": '11:15', "original_time": '11:15', "status": "confirmed", "kind": "existing"},
        {"customer": "Arjun", "role": "Existing confirmed patient", "branch": "Northstar Central",
         "time": '11:50', "original_time": '11:50', "status": "confirmed", "kind": "existing"},
        {"customer": "Meera", "role": "Waitlisted at Northstar Central", "branch": "Northstar Central",
         "time": None, "original_time": None, "status": "waiting", "kind": "waitlist"},
    ]
    log = [f"{fmt(NOW)} · Fictional traffic ETA to Northstar Central: {central_eta} min (arrival {fmt(arrival_central)})."]
    checked = []
    eligible = []
    for branch in branches:
        arrival = NOW + branch['travel_minutes']
        feasible = []
        for starts in branch['slots']:
            if starts > ORIGINAL + max_delay_minutes:
                continue
            if arrival + BUFFER > starts:
                continue
            if not branch['qualified']:
                continue
            feasible.append(starts)
        if not branch['qualified']:
            note = 'Rejected: this doctor is not qualified for the booked service'
        elif not branch['slots']:
            note = 'Rejected: no free appointment; confirmed patients are not displaced'
        elif not feasible:
            note = 'Rejected: cannot arrive five minutes before an eligible slot within the delay cap'
        else:
            note = f"Available appointment at {fmt(feasible[0])}"
        checked.append({"branch": branch['branch'], "travel_minutes": branch['travel_minutes'],
                        "predicted_arrival": fmt(arrival), "available_time": fmt(feasible[0]) if feasible else None,
                        "eligible": bool(feasible), "reason": note})
        if feasible:
            start = min(feasible)
            eligible.append({"branch": branch['branch'], "branch_id": branch['branch_id'],
                             "staff": branch['staff'], "time": fmt(start), "starts_minutes": start,
                             "arrival": fmt(arrival), "travel_minutes": branch['travel_minutes'],
                             "delay_minutes": start - ORIGINAL,
                             "finish_minutes": start + SERVICE_DURATION,
                             "reason": "Same clinic network, matching service, free qualified doctor, reachable slot"})
    # Arrival-to-completion time matters: a geographically nearest branch with a
    # much later appointment may waste more time than a slightly farther one.
    eligible.sort(key=lambda c: (c['finish_minutes'], c['travel_minutes'], c['starts_minutes']))
    selected = None
    if on_time:
        decision, outcome = 'keep_original', 'on_time'
        log.append(f"{fmt(arrival_central)} · Expected within {GRACE}-minute grace period. Do not reroute unnecessarily.")
    elif not auto_reroute_opt_in:
        decision, outcome = 'opt_in_required', 'opt_in_required'
        log.append('No booking-time permission for automatic branch transfers. Keep original appointment and alert customer.')
    elif eligible:
        selected = {k: v for k, v in eligible[0].items() if k != 'finish_minutes' and k != 'starts_minutes'}
        decision, outcome = 'auto_reroute', 'auto_rerouted'
        people[0].update(branch=selected['branch'], time=selected['time'], status='auto_rerouted')
        people[-1].update(time=fmt(ORIGINAL), status='offer_pending')
        log.append(f"Auto-reroute permission previously granted. Evaluated {len(branches)} branches without moving confirmed patients.")
        log.append(f"Rahul automatically assigned to {selected['branch']} at {selected['time']} (ETA {selected['travel_minutes']} min; travel arrival {selected['arrival']}).")
        log.append(f"Original 10:00 Central appointment released; Meera receives a separate, time-limited waitlist offer (not forced booking).")
        log.append('In production, both appointment changes and QR regeneration must happen atomically, followed by an immediate notification.')
    else:
        decision, outcome = 'no_safe_branch', 'manual_review'
        log.append('No qualified and reachable free slot within the selected delay cap. Original retained; notify customer and staff for review.')
    people.sort(key=lambda person: person['time'] or '99:99')
    return {
        'simulation_only': True,
        'traffic_provider': 'fictional travel times; not Google Maps live traffic',
        'scenario': scenario, 'clock': fmt(NOW), 'original_branch': 'Northstar Central',
        'original_time': fmt(ORIGINAL), 'original_travel_minutes': central_eta,
        'predicted_arrival': fmt(arrival_central), 'max_delay_minutes': max_delay_minutes,
        'auto_reroute_opt_in': auto_reroute_opt_in,
        'decision': decision, 'outcome': outcome, 'selected': selected,
        'branches_checked': checked,
        'confirmed_customers_displaced': 0,
        'waitlist_offer_created_in_demo': outcome == 'auto_rerouted',
        'customers': people, 'events': log,
        'policy': 'Auto-move only after prior authorization, within the same clinic network, same service and qualified staff. Never override a confirmed booking; fall back to manual review if no safe slot exists.'
    }
