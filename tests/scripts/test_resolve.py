"""The rules resolve.py refuses to bend.

Every test here is a refusal or a settled answer, not a happy path: assembling a
folder is test_build.py's job. The version rules are exercised by calling the
check functions with an explicit running version, so the real VERSION file is
never touched and the tests do not change meaning when Foundry is released.

Run: python3 -m unittest discover   (from the repo root)
"""

from __future__ import annotations

from pathlib import Path

from tests.repos import RepoCase, make_repo, needs, resolve


class FingerprintIsFrozen(RepoCase):
    """Every pin anyone has ever written is a fingerprint of a source checkout.

    So changing what a fingerprint covers does not fail: it silently gives a
    different answer, and every pin already published stops matching. These two
    tests exist to turn that into a loud failure, which forces the change to be
    a deliberate decision with a Foundry version bump behind it.
    """

    # Two shipped files, plus one example of each thing that is skipped: a name
    # (the manifest, and .DS_Store), a directory (__pycache__), a suffix (.pyc).
    SAMPLE = {
        "README.md": "readme\n",
        "skills/greet/SKILL.md": "greet\n",
        "foundry.plugin.yaml": "id: sample\n",
        ".DS_Store": "junk\n",
        "__pycache__/greet.cpython-311.pyc": "compiled\n",
        "skills/greet/SKILL.pyc": "compiled\n",
    }
    # sha256 over "README.md\0readme\n\0skills/greet/SKILL.md\0greet\n\0", first 12.
    SAMPLE_DIGEST = "518d7c109d4d"

    def tree(self, name: str = "sample") -> Path:
        root = self.workspace / name
        for relative, text in self.SAMPLE.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return root

    def test_a_known_tree_still_hashes_to_the_digest_it_has_always_hashed_to(self):
        self.assertEqual(resolve.fingerprint(self.tree()), self.SAMPLE_DIGEST)

        # The digest above only proves what these skip lists do to this one
        # tree. Pinning the lists themselves is what catches a new entry being
        # added, which would drop files this tree happens not to contain.
        #
        # `.foundry` was added before v0.1.0, and this assertion is what caught
        # the change rather than letting it through. The digest above did not
        # move, because this sample tree holds no cache. Every real plugin
        # repository holds one from its first build, and while it counted, the
        # same source pinned differently on a machine that had built before.
        self.assertEqual(
            sorted(resolve.SKIP_DIRS),
            [".claude", ".foundry", ".git", ".github", ".venv", "__pycache__", "node_modules"],
        )
        self.assertEqual(sorted(resolve.SKIP_SUFFIXES), [".pyc", ".pyo"])
        self.assertEqual(sorted(resolve.SKIP_NAMES), [".DS_Store", "foundry.plugin.yaml"])

    def test_a_skipped_file_is_outside_the_fingerprint_and_a_shipped_one_is_inside(self):
        root = self.tree()
        before = resolve.fingerprint(root)

        (root / "__pycache__" / "extra.pyc").write_bytes(b"more compiled bytes\n")
        self.assertEqual(
            resolve.fingerprint(root),
            before,
            "a file under a skipped directory changed the fingerprint",
        )

        (root / "skills" / "greet" / "reference.md").write_text("more\n")
        self.assertNotEqual(
            resolve.fingerprint(root),
            before,
            "a shipped file did not change the fingerprint",
        )


class PinRules(RepoCase):
    def test_a_pin_that_moves_is_rejected(self):
        """A pin names one exact build, so anything that can drift is refused."""
        make_repo(
            self.workspace,
            "library",
            files={"skills/audit/SKILL.md": "audit\n"},
        )
        consumer = make_repo(
            self.workspace,
            "consumer",
            requires=[{"id": "library", "pin": "latest", "path": "../library"}],
        )

        with self.assertRaises(resolve.ResolveError) as refusal:
            resolve.read_manifest(consumer)

        message = str(refusal.exception)
        self.assertIn("latest", message)
        self.assertIn("moves", message)
        self.assertIn("fingerprint", message)

    def test_two_dependencies_wanting_different_builds_stops_and_names_both(self):
        """No correct answer exists, so nothing is picked and both sides are named."""
        make_repo(self.workspace, "shared", files={"skills/shared/SKILL.md": "shared\n"})
        left = make_repo(
            self.workspace,
            "left",
            requires=[{"id": "shared", "pin": "aaaa1111aaaa", "path": "../shared"}],
        )
        right = make_repo(
            self.workspace,
            "right",
            requires=[{"id": "shared", "pin": "bbbb2222bbbb", "path": "../shared"}],
        )
        root = make_repo(self.workspace, "root", requires=[needs(left), needs(right)])

        with self.assertRaises(resolve.ResolveError) as refusal:
            resolve.resolve(root)

        message = str(refusal.exception)
        self.assertIn("DEPENDENCIES DISAGREE", message)
        self.assertIn("aaaa1111aaaa", message)
        self.assertIn("bbbb2222bbbb", message)
        self.assertIn("left", message)
        self.assertIn("right", message)
        self.assertIn("shared", message)


class FoundryVersionRules(RepoCase):
    def test_the_newest_version_anyone_asked_for_wins_and_no_other_is_used(self):
        """Never older than the highest request, never as new as the tool running."""
        dependency = make_repo(self.workspace, "library", foundry="0.1.4")
        root = make_repo(
            self.workspace,
            "root",
            foundry="0.1.0",
            requires=[needs(dependency)],
        )

        chosen = resolve.choose_foundry(resolve.collect(root), "0.9.9")

        self.assertEqual(chosen, "0.1.4")
        self.assertNotEqual(chosen, "0.9.9", "landed on a version nobody asked for")
        self.assertNotEqual(chosen, "0.1.0", "ignored the higher requirement")

    def test_needing_a_foundry_newer_than_this_one_stops_and_names_the_plugin(self):
        dependency = make_repo(self.workspace, "library", foundry="0.9.0")
        root = make_repo(self.workspace, "root", foundry="0.1.0", requires=[needs(dependency)])

        with self.assertRaises(resolve.ResolveError) as refusal:
            resolve.choose_foundry(resolve.collect(root), "0.1.0")

        message = str(refusal.exception)
        self.assertIn("FOUNDRY TOO OLD", message)
        self.assertIn("library", message)
        self.assertIn("0.9.0", message)
        self.assertIn(str(dependency / "foundry.plugin.yaml"), message)

    def test_needing_a_different_first_number_stops_and_names_a_migration(self):
        """A first-number change cannot be worked around, only migrated."""
        root = make_repo(self.workspace, "root", foundry="1.0.0")

        with self.assertRaises(resolve.ResolveError) as refusal:
            resolve.check_foundry_major(resolve.collect(root), "0.1.0")

        message = str(refusal.exception)
        self.assertIn("WRONG FOUNDRY GENERATION", message)
        self.assertIn("root", message)
        self.assertIn("docs/migrations/foundry-0-to-1.md", message)

    def test_the_migration_is_named_oldest_first_whichever_side_is_behind(self):
        """Only one document per pair of generations is ever written.

        The plugin can be ahead of the build tool or behind it, and both stop
        here. Naming the document in the order the two numbers happened to
        appear would send half of those refusals to a file nobody will write.
        """
        cases = {
            "ahead": ("3.0.0", "docs/migrations/foundry-2-to-3.md"),
            "behind": ("1.0.0", "docs/migrations/foundry-1-to-2.md"),
        }
        for plugin_id, (declared, document) in cases.items():
            with self.subTest(plugin_id):
                root = make_repo(self.workspace, plugin_id, foundry=declared)
                with self.assertRaises(resolve.ResolveError) as refusal:
                    resolve.check_foundry_major(resolve.collect(root), "2.0.0")
                self.assertIn(document, str(refusal.exception))


class DependencyWalk(RepoCase):
    def test_a_loop_is_reported_as_the_loop(self):
        """Not a stack overflow: the trail is printed so the cycle can be broken."""
        make_repo(
            self.workspace,
            "alpha",
            requires=[{"id": "beta", "pin": "0000cccc0000", "path": "../beta"}],
        )
        make_repo(
            self.workspace,
            "beta",
            requires=[{"id": "alpha", "pin": "0000dddd0000", "path": "../alpha"}],
        )

        with self.assertRaises(resolve.ResolveError) as refusal:
            resolve.collect(self.workspace / "alpha")

        message = str(refusal.exception)
        self.assertIn("DEPENDENCY LOOP", message)
        self.assertIn("alpha needs beta needs alpha", message)
