from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tweb.cookies import (
  load_cookie_file,
  load_firefox_cookie_jar,
  load_zen_cookie_jar,
  resolve_firefox_profile,
  resolve_zen_profile,
)


class CookieLoaderTest(unittest.TestCase):
  def test_load_cookie_file_auto_detects_json(self) -> None:
    with TemporaryDirectory() as temp_dir:
      cookie_path = Path(temp_dir) / "cookies.json"
      cookie_path.write_text(
        '[{"name":"sessionid","value":"abc123","domain":".example.com","path":"/","secure":true}]',
        encoding="utf-8",
      )

      jar = load_cookie_file(cookie_path)

    self.assertEqual(jar.get("sessionid", domain=".example.com", path="/"), "abc123")

  def test_load_cookie_file_auto_detects_netscape(self) -> None:
    with TemporaryDirectory() as temp_dir:
      cookie_path = Path(temp_dir) / "cookies.txt"
      cookie_path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t2147483647\tsid\tabc123\n",
        encoding="utf-8",
      )

      jar = load_cookie_file(cookie_path)

    self.assertEqual(jar.get("sid", domain=".example.com", path="/"), "abc123")

  def test_resolve_firefox_profile_prefers_default_profile(self) -> None:
    with TemporaryDirectory() as temp_dir:
      firefox_dir = Path(temp_dir) / "Library" / "Application Support" / "Firefox"
      firefox_dir.mkdir(parents=True)
      (firefox_dir / "Profiles" / "default-release").mkdir(parents=True)
      (firefox_dir / "profiles.ini").write_text(
        "[Profile0]\n"
        "Name=default-release\n"
        "IsRelative=1\n"
        "Path=Profiles/default-release\n"
        "Default=1\n",
        encoding="utf-8",
      )

      with patch("tweb.cookies.Path.home", return_value=Path(temp_dir)):
        profile_dir = resolve_firefox_profile()

    self.assertEqual(profile_dir, firefox_dir / "Profiles" / "default-release")

  def test_resolve_zen_profile_prefers_default_profile(self) -> None:
    with TemporaryDirectory() as temp_dir:
      zen_dir = Path(temp_dir) / "Library" / "Application Support" / "zen"
      zen_dir.mkdir(parents=True)
      (zen_dir / "Profiles" / "zen-default").mkdir(parents=True)
      (zen_dir / "profiles.ini").write_text(
        "[Profile0]\n"
        "Name=zen-default\n"
        "IsRelative=1\n"
        "Path=Profiles/zen-default\n"
        "Default=1\n",
        encoding="utf-8",
      )

      with patch("tweb.cookies.Path.home", return_value=Path(temp_dir)):
        profile_dir = resolve_zen_profile()

    self.assertEqual(profile_dir, zen_dir / "Profiles" / "zen-default")

  def test_resolve_zen_profile_prefers_installs_ini_default(self) -> None:
    with TemporaryDirectory() as temp_dir:
      zen_dir = Path(temp_dir) / "Library" / "Application Support" / "zen"
      zen_dir.mkdir(parents=True)
      (zen_dir / "Profiles" / "ui-default").mkdir(parents=True)
      (zen_dir / "Profiles" / "install-default").mkdir(parents=True)
      (zen_dir / "profiles.ini").write_text(
        "[Profile1]\n"
        "Name=Default Profile\n"
        "IsRelative=1\n"
        "Path=Profiles/ui-default\n"
        "Default=1\n\n"
        "[Profile0]\n"
        "Name=Default (release)\n"
        "IsRelative=1\n"
        "Path=Profiles/install-default\n",
        encoding="utf-8",
      )
      (zen_dir / "installs.ini").write_text(
        "[INSTALLHASH]\n"
        "Default=Profiles/install-default\n"
        "Locked=1\n",
        encoding="utf-8",
      )

      with patch("tweb.cookies.Path.home", return_value=Path(temp_dir)):
        profile_dir = resolve_zen_profile()

    self.assertEqual(profile_dir, zen_dir / "Profiles" / "install-default")

  def test_load_firefox_cookie_jar_reads_sqlite_profile(self) -> None:
    with TemporaryDirectory() as temp_dir:
      profile_dir = Path(temp_dir) / "profile"
      profile_dir.mkdir()
      db_path = profile_dir / "cookies.sqlite"
      connection = sqlite3.connect(db_path)
      try:
        connection.execute(
          "CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, isSecure INTEGER)"
        )
        connection.execute(
          "INSERT INTO moz_cookies VALUES (?, ?, ?, ?, ?, ?)",
          ("sessionid", "abc123", ".example.com", "/", 2147483647, 1),
        )
        connection.execute(
          "INSERT INTO moz_cookies VALUES (?, ?, ?, ?, ?, ?)",
          ("other", "skip", ".other.com", "/", 2147483647, 0),
        )
        connection.commit()
      finally:
        connection.close()

      jar = load_firefox_cookie_jar(profile=str(profile_dir), domains=["example.com"])

    self.assertEqual(jar.get("sessionid", domain=".example.com", path="/"), "abc123")
    self.assertIsNone(jar.get("other", domain=".other.com", path="/"))

  def test_load_zen_cookie_jar_reads_sqlite_profile(self) -> None:
    with TemporaryDirectory() as temp_dir:
      profile_dir = Path(temp_dir) / "profile"
      profile_dir.mkdir()
      db_path = profile_dir / "cookies.sqlite"
      connection = sqlite3.connect(db_path)
      try:
        connection.execute(
          "CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, isSecure INTEGER)"
        )
        connection.execute(
          "INSERT INTO moz_cookies VALUES (?, ?, ?, ?, ?, ?)",
          ("sessionid", "zen-value", ".example.com", "/", 2147483647, 1),
        )
        connection.commit()
      finally:
        connection.close()

      jar = load_zen_cookie_jar(profile=str(profile_dir), domains=["example.com"])

    self.assertEqual(jar.get("sessionid", domain=".example.com", path="/"), "zen-value")


if __name__ == "__main__":
  unittest.main()
