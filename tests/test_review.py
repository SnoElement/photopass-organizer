from dataclasses import replace
from datetime import UTC, date, datetime

from conftest import decided_config, write_jpeg, write_mp4

from photopass_organizer.config import Friend, PhotoOverride, ShareMethod, TripRule
from photopass_organizer.organizer import Organizer, PlaceMode
from photopass_organizer.review import (
    TRIP_GAP_DAYS,
    DayDecision,
    _rules_for_run,
    apply_decisions,
    build_state,
    decision_for,
    dry_run_counts,
    group_trips,
)
from photopass_organizer.shared import SharedFolderIndex

BATCH = "ecd5e910-484f-4b99-ac12-9fad86cefc89"
BATCH_B = "ece7d414-cd5e-4995-adf1-ccea11580c47"
EPCOT = "Epcot"
MAGIC_KINGDOM = "Magic Kingdom Park"


def bare_config(*rules):
    return replace(decided_config(None, None), trips=list(rules))


def decide(day, park, state, *friends):
    return DayDecision(date.fromisoformat(day), park, state, tuple(friends))


def test_group_trips_splits_on_gaps_longer_than_the_limit():
    keys = [("2026-10-10", EPCOT), ("2026-10-12", EPCOT), ("2026-10-20", EPCOT)]
    assert TRIP_GAP_DAYS == 2
    assert group_trips(keys) == [keys[:2], keys[2:]]


def test_decision_for_reads_the_matching_rule():
    config = bare_config(
        TripRule(date(2026, 10, 10), date(2026, 10, 10), ("Alex",), True),
        TripRule(date(2026, 10, 11), date(2026, 10, 11), ("Sam",), False),
        TripRule(date(2026, 10, 12), date(2026, 10, 12), (), False, ignore=True),
    )
    assert decision_for(config, date(2026, 10, 10), EPCOT) == decide(
        "2026-10-10", EPCOT, "mine", "Alex"
    )
    assert decision_for(config, date(2026, 10, 11), EPCOT) == decide(
        "2026-10-11", EPCOT, "friends", "Sam"
    )
    assert decision_for(config, date(2026, 10, 12), EPCOT).state == "ignored"
    assert decision_for(config, date(2026, 10, 13), EPCOT) == decide(
        "2026-10-13", EPCOT, "undecided"
    )


def test_apply_decisions_preserves_rules_for_dates_not_shown():
    existing = TripRule(date(2026, 10, 9), date(2026, 10, 14), ("Alex",), True)
    merged = apply_decisions(
        bare_config(existing), [decide("2026-11-01", EPCOT, "mine")]
    )
    assert merged.trips == [
        existing,
        TripRule(
            date(2026, 11, 1), date(2026, 11, 1), (), True, parks=frozenset({EPCOT})
        ),
    ]


def test_apply_decisions_splits_a_parkless_rule_when_parks_disagree():
    existing = TripRule(date(2026, 10, 10), date(2026, 10, 10), ("Alex",), True)
    merged = apply_decisions(
        bare_config(existing),
        [
            decide("2026-10-10", EPCOT, "mine"),
            decide("2026-10-10", MAGIC_KINGDOM, "friends", "Sam"),
        ],
    )
    assert merged.trips == [
        TripRule(
            date(2026, 10, 10), date(2026, 10, 10), (), True, parks=frozenset({EPCOT})
        ),
        TripRule(
            date(2026, 10, 10),
            date(2026, 10, 10),
            ("Sam",),
            False,
            parks=frozenset({MAGIC_KINGDOM}),
        ),
    ]


def test_apply_decisions_keeps_a_parkless_rule_when_parks_agree():
    existing = TripRule(date(2026, 10, 10), date(2026, 10, 10), ("Alex",), True)
    merged = apply_decisions(
        bare_config(existing),
        [
            decide("2026-10-10", EPCOT, "friends", "Sam"),
            decide("2026-10-10", MAGIC_KINGDOM, "friends", "Sam"),
        ],
    )
    assert merged.trips == [
        TripRule(date(2026, 10, 10), date(2026, 10, 10), ("Sam",), False)
    ]


def test_apply_decisions_merges_consecutive_identical_days():
    merged = apply_decisions(
        bare_config(),
        [decide(f"2026-10-{day}", EPCOT, "friends", "Alex") for day in (10, 11, 12)],
    )
    assert merged.trips == [
        TripRule(
            date(2026, 10, 10),
            date(2026, 10, 12),
            ("Alex",),
            False,
            parks=frozenset({EPCOT}),
        )
    ]


def test_apply_decisions_does_not_merge_across_a_longer_gap_or_different_answers():
    merged = apply_decisions(
        bare_config(),
        [
            decide("2026-10-10", EPCOT, "mine"),
            decide("2026-10-11", EPCOT, "friends", "Alex"),
            decide("2026-10-20", EPCOT, "friends", "Alex"),
        ],
    )
    assert [(rule.start.day, rule.end.day) for rule in merged.trips] == [
        (10, 10),
        (11, 11),
        (20, 20),
    ]


def test_apply_decisions_drops_undecided():
    existing = TripRule(date(2026, 10, 10), date(2026, 10, 11), ("Alex",), True)
    merged = apply_decisions(
        bare_config(existing), [decide("2026-10-10", EPCOT, "undecided")]
    )
    assert merged.trips == [
        TripRule(date(2026, 10, 11), date(2026, 10, 11), ("Alex",), True)
    ]


def test_apply_decisions_explicit_undecided_day_breaks_a_rule_run():
    existing = TripRule(date(2026, 10, 10), date(2026, 10, 12), ("Alex",), True)
    merged = apply_decisions(
        bare_config(existing), [decide("2026-10-11", EPCOT, "undecided")]
    )
    assert merged.trips == [
        TripRule(date(2026, 10, 10), date(2026, 10, 10), ("Alex",), True),
        TripRule(date(2026, 10, 12), date(2026, 10, 12), ("Alex",), True),
    ]


def test_apply_decisions_does_not_bridge_an_unreviewed_gap_day():
    merged = apply_decisions(
        bare_config(),
        [
            decide("2026-10-10", EPCOT, "friends", "Alex"),
            decide("2026-10-12", EPCOT, "friends", "Alex"),
        ],
    )
    assert [(rule.start.day, rule.end.day) for rule in merged.trips] == [
        (10, 10),
        (12, 12),
    ]


def test_apply_decisions_empty_save_leaves_disjoint_identical_rules_alone():
    rules = [
        TripRule(date(2026, 3, 1), date(2026, 3, 3), (), False, ignore=True),
        TripRule(date(2026, 3, 5), date(2026, 3, 6), (), False, ignore=True),
    ]
    assert apply_decisions(bare_config(*rules), []).trips == rules
    friend_rules = [
        TripRule(date(2026, 4, 1), date(2026, 4, 2), ("Alex",), False),
        TripRule(date(2026, 4, 4), date(2026, 4, 4), ("Alex",), False),
    ]
    assert apply_decisions(bare_config(*friend_rules), []).trips == friend_rules


def test_apply_decisions_new_single_park_decision_is_park_scoped():
    merged = apply_decisions(bare_config(), [decide("2026-05-01", EPCOT, "ignored")])
    assert merged.trips == [
        TripRule(
            date(2026, 5, 1),
            date(2026, 5, 1),
            (),
            False,
            parks=frozenset({EPCOT}),
            ignore=True,
        )
    ]


def test_rules_for_run_lets_a_parkless_entry_win_over_a_park_with_the_same_answer():
    value = ("friends", ("Alex",))
    day = date(2026, 10, 10)
    expected = [TripRule(day, day, ("Alex",), False)]
    assert _rules_for_run(day, day, {None: value, EPCOT: value}) == expected
    assert _rules_for_run(day, day, {EPCOT: value, None: value}) == expected


def test_apply_decisions_ignored_day_writes_ignore_rule():
    merged = apply_decisions(bare_config(), [decide("2026-10-10", EPCOT, "ignored")])
    assert merged.trips == [
        TripRule(
            date(2026, 10, 10),
            date(2026, 10, 10),
            (),
            False,
            parks=frozenset({EPCOT}),
            ignore=True,
        )
    ]


def write_epcot(downloads, name, clock, seed, **kwargs):
    return write_jpeg(
        downloads / BATCH / f"2026-10-10 - Epcot - {name}.jpeg",
        f"2026:10:10 {clock}",
        "-04:00",
        seed=seed,
        **kwargs,
    )


def organizer_for(tmp_path, *, rules=(), shared=None, photos=None):
    downloads = tmp_path / "Downloads"
    config = decided_config(downloads, tmp_path / "PhotoPass")
    friends = {
        name: Friend(name, ShareMethod.FOLDER, path=folder)
        for name, folder in (shared or {}).items()
    }
    config = replace(config, trips=list(rules), photos=photos or {}, friends=friends)
    index = SharedFolderIndex.load(shared or {})
    return Organizer(
        config,
        tmp_path / "state",
        mode=PlaceMode.COPY,
        dry_run=True,
        shared_index=index,
    )


def state_for(organizer):
    plan = organizer.plan()
    return build_state(
        plan,
        organizer.config,
        organizer.shared_index,
        organizer.ledger,
        organizer.destination_hashes(),
    )


def test_build_state_hides_handled_and_counts_undecided(tmp_path):
    downloads = tmp_path / "Downloads"
    first = write_epcot(downloads, "Italy", "14:00:00", seed=1)
    write_epcot(downloads, "Germany", "15:00:00", seed=2)
    organizer = organizer_for(tmp_path)
    from photopass_organizer.media import hash_file

    organizer.ledger.record_placed(
        hash_file(first), tmp_path / "PhotoPass" / first.name
    )
    state = state_for(organizer)

    assert state["undecided_count"] == 1
    (trip,) = state["trips"]
    assert (trip["start"], trip["end"], trip["resort"]) == (
        "2026-10-10",
        "2026-10-10",
        "Walt Disney World",
    )
    (day,) = trip["days"]
    assert day["date"] == "2026-10-10" and day["park"] == EPCOT
    assert day["decision"] == {"state": "undecided", "friends": []}
    assert day["handled_count"] == 1
    assert len(day["handled"]) == 1 and len(day["new"]) == 1
    assert day["new"][0]["name"] == "2026-10-10 - Epcot - Germany.jpeg"
    assert day["new"][0]["time"] == "15:00"
    assert day["new"][0]["is_video"] is False
    assert day["new"][0]["paired_still"] is None


def test_build_state_preticks_friends_whose_folder_holds_a_photo(tmp_path):
    downloads = tmp_path / "Downloads"
    held = write_epcot(downloads, "Italy", "14:00:00", seed=1)
    write_epcot(downloads, "Germany", "15:00:00", seed=2)
    folder = tmp_path / "Shared" / "Alex"
    folder.mkdir(parents=True)
    (folder / held.name).write_bytes(held.read_bytes())
    state = state_for(organizer_for(tmp_path, shared={"Alex": folder}))
    (day,) = state["trips"][0]["days"]
    assert day["preticked"] == ["Alex"]
    assert day["handled_count"] == 1
    assert state["friends"] == [
        {"name": "Alex", "share": "folder", "location": str(folder)}
    ]


def test_build_state_marks_ignored_photo(tmp_path):
    from photopass_organizer.media import hash_file

    downloads = tmp_path / "Downloads"
    ignored = write_epcot(downloads, "Italy", "14:00:00", seed=1)
    write_epcot(downloads, "Germany", "15:00:00", seed=2)
    photos = {hash_file(ignored): PhotoOverride(hash_file(ignored), "ignore")}
    state = state_for(organizer_for(tmp_path, photos=photos))
    (day,) = state["trips"][0]["days"]
    assert [
        (entry["name"].split(" - ")[-1], entry["ignored"]) for entry in day["new"]
    ] == [("Italy.jpeg", True), ("Germany.jpeg", False)]


def test_build_state_lists_stock_art_with_its_keep_override(tmp_path):
    downloads = tmp_path / "Downloads"
    write_epcot(downloads, "Stock", "14:30:00", seed=2, icc=True)
    write_epcot(downloads, "Italy", "14:00:00", seed=1)
    state = state_for(organizer_for(tmp_path))
    assert [
        (entry["name"].split(" - ")[-1], entry["keep"]) for entry in state["stock"]
    ] == [("Stock.jpeg", False)]
    assert len(state["trips"][0]["days"][0]["new"]) == 1

    organizer = organizer_for(tmp_path)
    plan = organizer.plan()
    stock_item = next(item for item in plan.items if item.is_stock)
    config = replace(
        organizer.config,
        photos={
            stock_item.content_hash: PhotoOverride(stock_item.content_hash, "keep")
        },
    )
    kept_state = build_state(
        plan, config, organizer.shared_index, organizer.ledger, set()
    )
    assert [entry["keep"] for entry in kept_state["stock"]] == [True]


def test_build_state_keeps_a_kept_stock_photo_in_the_stock_list(tmp_path):
    from photopass_organizer.media import hash_file

    downloads = tmp_path / "Downloads"
    stock = write_epcot(downloads, "Stock", "14:30:00", seed=2, icc=True)
    write_epcot(downloads, "Italy", "14:00:00", seed=1)
    photos = {hash_file(stock): PhotoOverride(hash_file(stock), "keep")}
    organizer = organizer_for(tmp_path, photos=photos)
    assert not any(item.is_stock for item in organizer.plan().items)
    state = state_for(organizer)
    assert [(entry["hash"], entry["keep"]) for entry in state["stock"]] == [
        (hash_file(stock), True)
    ]
    (day,) = state["trips"][0]["days"]
    listed = [entry["hash"] for entry in day["new"] + day["handled"]]
    assert hash_file(stock) not in listed
    assert len(listed) == 1


def test_build_state_pairs_batch_video_with_nearest_still(tmp_path):
    downloads = tmp_path / "Downloads"
    write_epcot(downloads, "Morning", "09:00:00", seed=1)
    near = write_epcot(downloads, "Afternoon", "14:00:00", seed=2)
    write_mp4(
        downloads / BATCH / "2026-10-10 - Epcot - Ride.mp4",
        datetime(2026, 10, 10, 18, 10, 0, tzinfo=UTC),
        seed=3,
    )
    state = state_for(organizer_for(tmp_path))
    (day,) = state["trips"][0]["days"]
    from photopass_organizer.media import hash_file

    video = next(entry for entry in day["new"] if entry["is_video"])
    assert video["time"] == "14:10"
    assert video["paired_still"] == hash_file(near)


def test_build_state_pairs_loose_video_with_the_still_it_was_dated_by(tmp_path):
    from photopass_organizer.media import hash_file

    downloads = tmp_path / "Downloads"
    still = write_epcot(downloads, "Afternoon", "14:00:00", seed=2)
    write_mp4(
        downloads / "2266277915.mp4",
        datetime(2026, 10, 10, 18, 5, 0, tzinfo=UTC),
        seed=3,
    )
    state = state_for(organizer_for(tmp_path))
    (day,) = state["trips"][0]["days"]
    video = next(entry for entry in day["new"] if entry["is_video"])
    assert video["paired_still"] == hash_file(still)


def test_build_state_dedupes_identical_content(tmp_path):
    downloads = tmp_path / "Downloads"
    write_epcot(downloads, "Italy", "14:00:00", seed=1)
    write_jpeg(
        downloads / BATCH_B / "2026-10-10 - Epcot - Italy_2.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    state = state_for(organizer_for(tmp_path))
    (day,) = state["trips"][0]["days"]
    assert len(day["new"]) == 1


def test_build_state_reports_decided_days(tmp_path):
    downloads = tmp_path / "Downloads"
    write_epcot(downloads, "Italy", "14:00:00", seed=1)
    rule = TripRule(date(2026, 10, 10), date(2026, 10, 10), ("Alex",), False)
    folder = tmp_path / "Shared" / "Alex"
    folder.mkdir(parents=True)
    state = state_for(organizer_for(tmp_path, rules=[rule], shared={"Alex": folder}))
    assert state["undecided_count"] == 0
    assert state["trips"][0]["days"][0]["decision"] == {
        "state": "friends",
        "friends": ["Alex"],
    }


def test_dry_run_counts(tmp_path):
    downloads = tmp_path / "Downloads"
    write_epcot(downloads, "Italy", "14:00:00", seed=1)
    write_epcot(downloads, "Germany", "14:10:00", seed=2)
    write_epcot(downloads, "Mexico", "14:20:00", seed=3)
    write_epcot(downloads, "Norway", "14:30:00", seed=4)
    write_jpeg(
        downloads / BATCH_B / "2026-10-10 - Epcot - Italy_2.jpeg",
        "2026:10:10 14:00:00",
        "-04:00",
        seed=1,
    )
    write_epcot(downloads, "Stock", "14:40:00", seed=5, icc=True)
    write_jpeg(
        downloads / BATCH / "2026-10-11 - Epcot - Japan.jpeg",
        "2026:10:11 10:00:00",
        "-04:00",
        seed=6,
    )
    write_jpeg(
        downloads / BATCH / "2026-10-12 - Epcot - France.jpeg",
        "2026:10:12 10:00:00",
        "-04:00",
        seed=7,
    )
    write_jpeg(
        downloads / BATCH / "2026-10-13 - Epcot - China.jpeg",
        "2026:10:13 10:00:00",
        "-04:00",
        seed=8,
    )
    shared = tmp_path / "Shared" / "Alex"
    shared.mkdir(parents=True)
    rules = [
        TripRule(date(2026, 10, 10), date(2026, 10, 10), ("Alex",), True),
        TripRule(date(2026, 10, 11), date(2026, 10, 11), ("Alex",), False),
        TripRule(date(2026, 10, 12), date(2026, 10, 12), (), False, ignore=True),
    ]
    organizer = organizer_for(tmp_path, rules=rules, shared={"Alex": shared})
    assert dry_run_counts(organizer) == {
        "share": {"Alex": 5},
        "keep": 4,
        "delete": 1,
        "ignore": 1,
        "duplicates": 1,
        "stock": 1,
        "undecided": 1,
    }
