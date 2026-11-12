"""Pure functions behind the review page: the state it shows and the day decisions it writes back."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta

from .config import Config, ConfigError, ShareMethod, TripRule
from .ledger import Ledger
from .media import park_timezone_name, resort_name
from .organizer import ActionKind, MediaItem, Organizer, Plan
from .shared import SharedFolderIndex

TRIP_GAP_DAYS = 2
IGNORE_ACTION = "ignore"
KEEP_ACTION = "keep"
DECISION_STATES = ("undecided", "mine", "friends", "ignored")
IGNORE_REASONS = ("ignored photo", "ignored day")
UNDECIDED_REASON = "undecided"

DecisionValue = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class DayDecision:
    date: date
    park: str
    state: str
    friends: tuple[str, ...]


def group_trips(day_keys: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    trips: list[list[tuple[str, str]]] = []
    for key in sorted(day_keys):
        current_date = date.fromisoformat(key[0])
        if (
            trips
            and (current_date - date.fromisoformat(trips[-1][-1][0])).days
            <= TRIP_GAP_DAYS
        ):
            trips[-1].append(key)
        else:
            trips.append([key])
    return trips


def _rule_value(rule: TripRule) -> DecisionValue:
    if rule.ignore:
        return "ignored", ()
    return ("mine" if rule.i_was_there else "friends"), rule.friends


def decision_for(config: Config, local_date: date, park: str) -> DayDecision:
    rule = config.rule_for(local_date, park)
    if rule is None:
        return DayDecision(local_date, park, "undecided", ())
    state, friends = _rule_value(rule)
    return DayDecision(local_date, park, state, friends)


def _expand_rules(rules: list[TripRule]) -> dict[date, dict[str | None, DecisionValue]]:
    by_date: dict[date, dict[str | None, DecisionValue]] = defaultdict(dict)
    for rule in rules:
        value = _rule_value(rule)
        for offset in range((rule.end - rule.start).days + 1):
            entry = by_date[rule.start + timedelta(days=offset)]
            for park in rule.parks if rule.parks is not None else (None,):
                entry[park] = value
    return by_date


def _overlay(
    existing: dict[str | None, DecisionValue], given: dict[str, DecisionValue]
) -> dict[str | None, DecisionValue]:
    if existing and len(set(given.values())) == 1 and set(existing) <= {None}:
        return {None: next(iter(given.values()))}
    merged = {park: value for park, value in existing.items() if park is not None}
    merged.update(given)
    return merged


def _rules_for_run(
    start: date, end: date, entry: dict[str | None, DecisionValue]
) -> list[TripRule]:
    parkless_values = {value for park, value in entry.items() if park is None}
    parks_by_value: dict[DecisionValue, set[str] | None] = {
        value: None for value in parkless_values
    }
    for park, value in entry.items():
        if park is not None and value not in parkless_values:
            parks_by_value.setdefault(value, set()).add(park)
    rules = []
    for (state, friends), parks in parks_by_value.items():
        frozen_parks = None if parks is None else frozenset(parks)
        if state == "ignored":
            rules.append(
                TripRule(start, end, (), False, parks=frozen_parks, ignore=True)
            )
        else:
            rules.append(
                TripRule(start, end, friends, state == "mine", parks=frozen_parks)
            )
    return rules


def apply_decisions(config: Config, decisions: list[DayDecision]) -> Config:
    by_date = _expand_rules(config.trips)
    given_by_date: dict[date, dict[str, DecisionValue]] = defaultdict(dict)
    for decision in decisions:
        if decision.state not in DECISION_STATES:
            raise ValueError(f"unknown decision state {decision.state!r}")
        given_by_date[decision.date][decision.park] = (decision.state, decision.friends)
    for day, given in given_by_date.items():
        by_date[day] = _overlay(by_date.get(day, {}), given)

    def decided(
        entry: dict[str | None, DecisionValue],
    ) -> dict[str | None, DecisionValue]:
        return {park: value for park, value in entry.items() if value[0] != "undecided"}

    rules: list[TripRule] = []
    run: tuple[date, date, dict[str | None, DecisionValue]] | None = None
    for day in sorted(by_date):
        entry = decided(by_date[day])
        if not entry:
            continue
        if run is not None and run[2] == entry and (day - run[1]).days == 1:
            run = (run[0], day, entry)
            continue
        if run is not None:
            rules.extend(_rules_for_run(*run))
        run = (day, day, entry)
    if run is not None:
        rules.extend(_rules_for_run(*run))
    rules.sort(key=lambda rule: (rule.start, tuple(sorted(rule.parks or ()))))
    return replace(config, trips=rules)


def dry_run_counts(organizer: Organizer) -> dict:
    counts = {
        "share": Counter(),
        "keep": 0,
        "delete": 0,
        "ignore": 0,
        "duplicates": 0,
        "stock": 0,
        "undecided": 0,
    }
    for action in organizer.plan().actions:
        if action.kind is ActionKind.SHARE:
            counts["share"][action.friend] += 1
        elif action.kind is ActionKind.PLACE:
            counts["keep"] += 1
        elif action.kind is ActionKind.DELETE:
            counts["ignore" if action.reason in IGNORE_REASONS else "delete"] += 1
        elif action.kind is ActionKind.DUPLICATE:
            counts["duplicates"] += 1
        elif action.kind is ActionKind.STOCK:
            counts["stock"] += 1
        elif action.kind is ActionKind.SKIP and action.reason == UNDECIDED_REASON:
            counts["undecided"] += 1
    counts["share"] = dict(counts["share"])
    return counts


def _friend_entries(config: Config, shared_index: SharedFolderIndex) -> list[dict]:
    entries = []
    for name in sorted(set(config.known_friends()) | set(shared_index.friends)):
        try:
            friend = config.friend(name)
        except ConfigError:
            entries.append(
                {"name": name, "share": ShareMethod.FOLDER.value, "location": ""}
            )
            continue
        location = (
            friend.album if friend.share is ShareMethod.PHOTOS_ALBUM else friend.path
        )
        entries.append(
            {"name": name, "share": friend.share.value, "location": str(location or "")}
        )
    return entries


def _paired_still_hash(
    video: MediaItem, day_items: list[MediaItem], hash_by_source: dict
) -> str | None:
    if video.paired_still is not None and video.paired_still in hash_by_source:
        return hash_by_source[video.paired_still]
    stills = [item for item in day_items if not item.is_video]
    nearest = min(
        stills,
        key=lambda still: abs(still.captured_at - video.captured_at),
        default=None,
    )
    return nearest.content_hash if nearest is not None else None


def build_state(
    plan: Plan,
    config: Config,
    shared_index: SharedFolderIndex,
    ledger: Ledger,
    destination_hashes: set[str],
) -> dict:
    groups: dict[tuple[str, str], list[MediaItem]] = defaultdict(list)
    stock = []
    seen: set[str] = set()
    for item in sorted(
        plan.items, key=lambda media: (media.captured_at, media.source.name)
    ):
        if item.content_hash in seen:
            continue
        seen.add(item.content_hash)
        override = config.photos.get(item.content_hash)
        kept = override is not None and override.action == KEEP_ACTION
        if item.is_stock or kept:
            stock.append(
                {"hash": item.content_hash, "name": item.source.name, "keep": kept}
            )
        elif item.local_date and item.park:
            groups[(item.local_date, item.park)].append(item)
    hash_by_source = {item.source: item.content_hash for item in plan.items}

    def is_handled(item: MediaItem) -> bool:
        return (
            item.content_hash in ledger
            or item.content_hash in destination_hashes
            or bool(shared_index.friends_holding(item.source.name, item.size_bytes))
        )

    def entry(item: MediaItem, day_items: list[MediaItem]) -> dict:
        override = config.photos.get(item.content_hash)
        return {
            "hash": item.content_hash,
            "name": item.source.name,
            "is_video": item.is_video,
            "time": item.captured_at.strftime("%H:%M"),
            "ignored": override is not None and override.action == IGNORE_ACTION,
            "paired_still": _paired_still_hash(item, day_items, hash_by_source)
            if item.is_video
            else None,
        }

    days_by_key = {}
    for key, day_items in groups.items():
        decision = decision_for(config, date.fromisoformat(key[0]), key[1])
        handled_items = [item for item in day_items if is_handled(item)]
        new_items = [item for item in day_items if not is_handled(item)]
        holders = {
            friend
            for item in day_items
            for friend in shared_index.friends_holding(
                item.source.name, item.size_bytes
            )
        }
        days_by_key[key] = {
            "date": key[0],
            "park": key[1],
            "label": next((item.event for item in day_items if item.event), key[1]),
            "decision": {"state": decision.state, "friends": list(decision.friends)},
            "preticked": sorted(holders),
            "new": [entry(item, day_items) for item in new_items],
            "handled": [entry(item, day_items) for item in handled_items],
            "handled_count": len(handled_items),
        }
    trips = []
    for trip_keys in group_trips(list(days_by_key)):
        first_park = trip_keys[0][1]
        timezone_name = park_timezone_name(
            first_park, config.settings.default_timezone, config.settings.parks
        )
        trips.append(
            {
                "start": trip_keys[0][0],
                "end": trip_keys[-1][0],
                "resort": resort_name(timezone_name),
                "days": [days_by_key[key] for key in trip_keys],
            }
        )
    undecided = sum(
        1 for day in days_by_key.values() if day["decision"]["state"] == "undecided"
    )
    return {
        "friends": _friend_entries(config, shared_index),
        "trips": trips,
        "stock": stock,
        "undecided_count": undecided,
    }
