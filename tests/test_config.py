import sys
from pathlib import Path

import pytest

from photopass_organizer.config import (
    Config,
    ConfigError,
    Friend,
    Settings,
    ShareMethod,
    load_config,
    parse_config,
    render_config,
    state_dir,
    write_config,
)

FULL_TOML = """
[settings]
source = "~/Downloads"
destination = "~/Pictures/PhotoPass"
default_timezone = "America/New_York"
stock_art = "delete"
shared_root = "~/Library/Mobile Documents/com~apple~CloudDocs/Shared Photos"
import_to_photos = true
photos_folder = "PhotoPass"
purge_after_import = true

[parks]
"Disneyland Paris" = "Europe/Paris"
"Tokyo Disneyland" = "Asia/Tokyo"

[friends.Alex]
share = "folder"
path = "~/Dropbox/Shared Photos/Alex"

[friends.Sam]
share = "photos-album"
album = "Sam"

[[trip]]
start = "2026-10-09"
end = "2026-10-14"
friends = ["Alex"]
i_was_there = false
parks = ["Epcot"]

[[trip]]
start = "2026-03-02"
ignore = true

[[photo]]
hash = "sha256:abc"
action = "ignore"
name = "2026-10-14 - Epcot - Test Track_3.jpeg"
"""


@pytest.fixture
def on_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")


def test_parse_full_config_and_round_trip(tmp_path, on_macos):
    config = parse_config(FULL_TOML, tmp_path)
    assert config.settings.destination == Path("~/Pictures/PhotoPass").expanduser()
    assert config.settings.parks["Disneyland Paris"] == "Europe/Paris"
    assert config.friends["Alex"].share is ShareMethod.FOLDER
    assert (
        config.friends["Alex"].path == Path("~/Dropbox/Shared Photos/Alex").expanduser()
    )
    assert (
        config.friends["Sam"].share is ShareMethod.PHOTOS_ALBUM
        and config.friends["Sam"].album == "Sam"
    )
    assert (
        config.trips[1].ignore is True
        and config.trips[1].friends == ()
        and config.trips[1].i_was_there is False
    )
    assert config.photos["sha256:abc"].action == "ignore"
    write_config(config, tmp_path / "photopass.toml")
    again = load_config(tmp_path / "photopass.toml")
    assert again == config
    assert (
        (tmp_path / "photopass.toml")
        .read_text(encoding="utf-8")
        .startswith("# Written by photopass-organizer")
    )


def test_write_config_keeps_previous_as_bak(tmp_path, on_macos):
    path = tmp_path / "photopass.toml"
    first = parse_config(FULL_TOML, tmp_path)
    write_config(first, path)
    first_text = path.read_text(encoding="utf-8")
    second = parse_config(
        '[[trip]]\nstart = "2026-01-01"\nfriends = ["Jordan"]\n', tmp_path
    )
    write_config(second, path)
    assert path.with_suffix(".toml.bak").read_text(encoding="utf-8") == first_text
    assert path.read_text(encoding="utf-8") != first_text
    assert not list(tmp_path.glob("*.tmp"))


def test_relative_paths_resolve_against_base_dir(tmp_path):
    config = parse_config(
        '[settings]\nsource = "incoming"\n[friends.Alex]\npath = "alex"\n', tmp_path
    )
    assert config.settings.source == tmp_path / "incoming"
    assert config.friends["Alex"].path == tmp_path / "alex"


def test_load_config_resolves_against_file_directory(tmp_path):
    (tmp_path / "photopass.toml").write_text(
        '[settings]\ndestination = "out"\n', encoding="utf-8"
    )
    assert (
        load_config(tmp_path / "photopass.toml").settings.destination
        == tmp_path / "out"
    )


def test_load_config_missing_file_gives_platform_defaults(tmp_path):
    config = load_config(tmp_path / "absent.toml")
    assert config.settings == Settings.platform_defaults()
    assert config.trips == [] and config.friends == {} and config.photos == {}


def test_ignore_trip_may_not_name_friends():
    with pytest.raises(ConfigError, match="ignore"):
        parse_config(
            '[[trip]]\nstart = "2026-03-02"\nignore = true\nfriends = ["Alex"]\n'
        )
    with pytest.raises(ConfigError, match="ignore"):
        parse_config(
            '[[trip]]\nstart = "2026-03-02"\nignore = true\ni_was_there = true\n'
        )


def test_unknown_share_method_is_config_error():
    with pytest.raises(ConfigError, match="Alex"):
        parse_config('[friends.Alex]\nshare = "email"\n')


@pytest.mark.parametrize(
    "text, table",
    [
        ("[settings]\nbogus = 1\n", "settings"),
        ('[friends.Alex]\nshare = "folder"\nbogus = 1\n', "friends.Alex"),
        (
            '[[trip]]\nstart = "2026-01-01"\n[[trip]]\nstart = "2026-02-01"\nbogus = 1\n',
            "trip 2",
        ),
        ('[[photo]]\nhash = "sha256:a"\naction = "keep"\nbogus = 1\n', "photo 1"),
        ("[mystery]\nx = 1\n", "mystery"),
    ],
)
def test_unknown_keys_name_the_table(text, table):
    with pytest.raises(ConfigError, match=table):
        parse_config(text)


def test_folder_friend_without_path_or_shared_root_is_config_error(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sys, "platform", "linux")
    config = parse_config("", tmp_path)
    assert config.settings.shared_root is None
    with pytest.raises(ConfigError, match="Jordan"):
        config.friend("Jordan")


def test_implicit_friend_uses_shared_root(tmp_path):
    config = parse_config('[settings]\nshared_root = "shared"\n', tmp_path)
    friend = config.friend("Jordan")
    assert (
        friend.share is ShareMethod.FOLDER
        and friend.path == tmp_path / "shared" / "Jordan"
    )


def test_folder_friend_entry_without_path_falls_back_to_shared_root(tmp_path):
    config = parse_config(
        '[settings]\nshared_root = "shared"\n[friends.Jordan]\nshare = "folder"\n',
        tmp_path,
    )
    assert config.friend("Jordan").path == tmp_path / "shared" / "Jordan"


def test_folder_friends_includes_implicit_and_skips_albums(tmp_path, on_macos):
    config = parse_config(
        '[settings]\nshared_root = "shared"\n'
        '[friends.Alex]\npath = "elsewhere"\n[friends.Sam]\nshare = "photos-album"\n'
        '[[trip]]\nstart = "2026-01-01"\nfriends = ["Jordan", "Sam"]\n',
        tmp_path,
    )
    assert config.folder_friends() == {
        "Alex": tmp_path / "elsewhere",
        "Jordan": tmp_path / "shared" / "Jordan",
    }


def test_folder_friends_raises_for_trip_friend_without_destination(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(sys, "platform", "linux")
    config = parse_config(
        '[[trip]]\nstart = "2026-01-01"\nfriends = ["Jordan"]\n', tmp_path
    )
    with pytest.raises(ConfigError, match="Jordan"):
        config.folder_friends()


def test_known_friends_merges_sources(tmp_path):
    shared = tmp_path / "shared"
    (shared / "Jordan").mkdir(parents=True)
    (shared / "Jordan" / "photo.jpeg").write_bytes(b"x")
    (shared / "notes.txt").write_text("not a friend", encoding="utf-8")
    config = parse_config(
        '[settings]\nshared_root = "shared"\n[friends.Alex]\npath = "a"\n'
        '[[trip]]\nstart = "2026-01-01"\nfriends = ["Sam"]\n',
        tmp_path,
    )
    assert config.known_friends() == ["Alex", "Jordan", "Sam"]


def test_known_friends_tolerates_missing_shared_root(tmp_path):
    config = parse_config(
        '[settings]\nshared_root = "nowhere"\n[friends.Alex]\npath = "a"\n', tmp_path
    )
    assert config.known_friends() == ["Alex"]


def test_photo_override_action_must_be_ignore_or_keep():
    with pytest.raises(ConfigError, match="photo 1"):
        parse_config('[[photo]]\nhash = "sha256:a"\naction = "delete"\n')
    with pytest.raises(ConfigError, match="photo 1"):
        parse_config('[[photo]]\naction = "keep"\n')
    config = parse_config('[[photo]]\nhash = "sha256:a"\naction = "keep"\n')
    assert config.photos["sha256:a"].name == ""


def test_photos_album_friend_off_macos_is_config_error(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ConfigError, match="Sam") as caught:
        parse_config('[friends.Sam]\nshare = "photos-album"\n')
    assert "macOS" in str(caught.value)


def test_state_dir_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("PHOTOPASS_ORGANIZER_HOME", raising=False)
    assert state_dir() == Path.home() / ".config" / "photopass-organizer"
    monkeypatch.setenv("PHOTOPASS_ORGANIZER_HOME", str(tmp_path / "env"))
    assert state_dir() == tmp_path / "env"
    assert state_dir(tmp_path / "flag") == tmp_path / "flag"


def test_platform_defaults(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    mac = Settings.platform_defaults()
    assert mac.import_to_photos is True
    assert (
        mac.shared_root
        == Path.home()
        / "Library"
        / "Mobile Documents"
        / "com~apple~CloudDocs"
        / "Shared Photos"
    )
    monkeypatch.setattr(sys, "platform", "linux")
    other = Settings.platform_defaults()
    assert other.import_to_photos is False and other.shared_root is None
    assert other.source == Path.home() / "Downloads"
    assert other.destination == Path.home() / "Pictures" / "PhotoPass"
    assert (other.default_timezone, other.stock_art, other.photos_folder) == (
        "America/New_York",
        "delete",
        "PhotoPass",
    )
    assert other.purge_after_import is True and other.parks == {}


def test_written_file_uses_table_arrays_for_trips_and_photos(tmp_path):
    config = parse_config(
        '[[trip]]\nstart = "2026-03-02"\nignore = true\n[[photo]]\nhash = "sha256:a"\naction = "keep"\n',
        tmp_path,
    )
    write_config(config, tmp_path / "photopass.toml")
    text = (tmp_path / "photopass.toml").read_text(encoding="utf-8")
    assert "[[trip]]" in text and "[[photo]]" in text
    assert load_config(tmp_path / "photopass.toml") == config


def test_empty_shared_root_means_none_and_round_trips(tmp_path, on_macos):
    config = parse_config('[settings]\nshared_root = ""\n', tmp_path)
    assert config.settings.shared_root is None
    write_config(config, tmp_path / "photopass.toml")
    assert 'shared_root = ""' in (tmp_path / "photopass.toml").read_text(
        encoding="utf-8"
    )
    assert load_config(tmp_path / "photopass.toml") == config


def test_duplicate_photo_hash_is_config_error():
    text = '[[photo]]\nhash = "sha256:x"\naction = "keep"\n[[photo]]\nhash = "sha256:y"\naction = "keep"\n[[photo]]\nhash = "sha256:x"\naction = "ignore"\n'
    with pytest.raises(ConfigError, match="photo 3: hash sha256:x already listed"):
        parse_config(text)


def test_write_config_validates_the_rendered_text_before_touching_the_disk(
    tmp_path, monkeypatch
):
    path = tmp_path / "photopass.toml"
    path.write_text("# original\n", encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "linux")
    config = Config(
        settings=Settings.platform_defaults(),
        friends={"Sam": Friend("Sam", ShareMethod.PHOTOS_ALBUM, album="Sam")},
    )
    with pytest.raises(ConfigError, match="macOS"):
        write_config(config, path)
    assert path.read_text(encoding="utf-8") == "# original\n"
    assert list(tmp_path.iterdir()) == [path]
    assert 'share = "photos-album"' in render_config(config)


@pytest.mark.parametrize(
    "text, fragment",
    [
        ('[[trip]]\nstart = "2026-10-09"\nfriends = "Alex"\n', "friends"),
        ('[[trip]]\nstart = "2026-10-09"\nfriends = [1, 2]\n', "friends"),
        ('[[trip]]\nstart = "2026-10-09"\nparks = "Epcot"\n', "parks"),
        ('[[trip]]\nstart = "2026-10-09"\nparks = [3]\n', "parks"),
        ('[[trip]]\nstart = "2026-10-09"\ni_was_there = "false"\n', "i_was_there"),
        ("[[trip]]\nstart = 20261009\n", "start"),
        ('[[trip]]\nstart = "2026-10-09"\nend = [1]\n', "end"),
    ],
)
def test_wrong_value_types_are_config_errors(text, fragment):
    with pytest.raises(ConfigError, match=fragment):
        parse_config(text)


def test_friend_only_rule_without_friends_is_config_error():
    with pytest.raises(ConfigError, match="no friends"):
        parse_config(
            '[[trip]]\nstart = "2026-10-09"\ni_was_there = false\nfriends = []\n'
        )
    with pytest.raises(ConfigError, match="no friends"):
        parse_config('[[trip]]\nstart = "2026-10-09"\ni_was_there = false\n')
    assert parse_config(
        '[[trip]]\nstart = "2026-10-09"\ni_was_there = false\nfriends = ["Alex"]\n'
    ).trips[0].friends == ("Alex",)
    assert (
        parse_config('[[trip]]\nstart = "2026-10-09"\nignore = true\n').trips[0].ignore
    )


def test_unquoted_toml_dates_are_still_accepted():
    config = parse_config("[[trip]]\nstart = 2026-10-09\n")
    assert config.trips[0].start.isoformat() == "2026-10-09"


def test_old_downloads_key_names_its_replacement(tmp_path):
    with pytest.raises(
        ConfigError, match="settings.downloads is now called settings.source"
    ):
        parse_config('[settings]\ndownloads = "incoming"\n', tmp_path)


def test_layout_setting_round_trips_and_rejects_unknown_values(tmp_path):
    assert parse_config("", tmp_path).settings.layout == "flat"
    config = parse_config('[settings]\nlayout = "park/date"\n', tmp_path)
    assert config.settings.layout == "park/date"
    path = tmp_path / "photopass.toml"
    write_config(config, path)
    assert load_config(path).settings.layout == "park/date"
    with pytest.raises(ConfigError, match="layout must be one of"):
        parse_config('[settings]\nlayout = "by-moon"\n', tmp_path)


def test_unknown_timezones_are_rejected(tmp_path):
    with pytest.raises(ConfigError, match="default_timezone must be an IANA timezone"):
        parse_config('[settings]\ndefault_timezone = "Mars/Olympus"\n', tmp_path)
    with pytest.raises(ConfigError, match="parks: Atlantis must be an IANA timezone"):
        parse_config('[parks]\nAtlantis = "Sea/Deep"\n', tmp_path)
    with pytest.raises(
        ConfigError, match="default_timezone must be a non-empty string"
    ):
        parse_config('[settings]\ndefault_timezone = ""\n', tmp_path)
