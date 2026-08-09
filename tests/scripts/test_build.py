"""What lands in a shipped folder, and what stops it being written at all.

The folder these tests inspect is the whole product: a user downloads it and
nothing else happens on their machine. So every assertion here is about the
folder's contents, not about how it was assembled.

Run: python3 -m unittest discover   (from the repo root)
"""

from __future__ import annotations

import filecmp
import json

from tests.repos import (
    MANIFEST_NAME,
    RUNNING_FOUNDRY,
    RepoCase,
    build,
    files_under,
    make_repo,
    needs,
    resolve,
)

LOCK_NAME = "foundry.lock.json"
METADATA_PATH = ".claude-plugin/plugin.json"


class PluginOnItsOwn(RepoCase):
    def test_a_plugin_with_no_dependencies_builds_and_ships_its_own_content(self):
        plugin = make_repo(
            self.workspace,
            "solo",
            description="Does one thing.",
            provides={"skills": ["greet"], "commands": ["hello.md"]},
            exclude=["tests", "notes"],
            files={
                "skills/greet/SKILL.md": "greet the caller\n",
                "commands/hello.md": "say hello\n",
                "README.md": "solo\n",
                "tests/test_greet.py": "assert True\n",
                "notes/scratch.md": "not for shipping\n",
            },
        )
        out = self.destination()

        build.build(plugin, out)

        self.assertEqual((out / "skills/greet/SKILL.md").read_text(), "greet the caller\n")
        self.assertEqual((out / "commands/hello.md").read_text(), "say hello\n")
        self.assertEqual((out / "README.md").read_text(), "solo\n")

        shipped = files_under(out)
        self.assertNotIn("tests/test_greet.py", shipped, "an excluded directory shipped")
        self.assertNotIn("notes/scratch.md", shipped, "an excluded directory shipped")
        self.assertNotIn(MANIFEST_NAME, shipped, "the manifest is build input, not product")

    def test_the_lock_and_the_metadata_hold_the_right_values(self):
        dependency = make_repo(
            self.workspace,
            "library",
            version="2.3.4",
            files={"skills/audit/SKILL.md": "audit\n"},
        )
        plugin = make_repo(
            self.workspace,
            "consumer",
            version="1.2.3",
            description="Takes an audit skill.",
            provides={"skills": ["audit"]},
            requires=[needs(dependency, take={"skills": ["audit"]})],
        )
        out = self.destination()

        build.build(plugin, out)

        lock = json.loads((out / LOCK_NAME).read_text())
        self.assertEqual(lock["plugin"], "consumer")
        self.assertEqual(lock["version"], "1.2.3")
        self.assertEqual(lock["foundry"], RUNNING_FOUNDRY)
        self.assertEqual(lock["built_with_foundry"], RUNNING_FOUNDRY)
        self.assertEqual(lock["took"], [{"from": "library", "item": "skills/audit"}])
        self.assertEqual(len(lock["contents"]), 12)
        self.assertEqual(
            lock["dependencies"],
            [
                {
                    "id": "library",
                    "version": "2.3.4",
                    "build": needs(dependency)["pin"],
                    "foundry_needs_at_least": RUNNING_FOUNDRY,
                }
            ],
        )

        metadata = json.loads((out / METADATA_PATH).read_text())
        self.assertEqual(metadata["name"], "consumer")
        self.assertEqual(metadata["version"], "1.2.3")
        self.assertEqual(metadata["description"], "Takes an audit skill.")

    def test_the_same_input_built_twice_gives_the_same_contents_fingerprint(self):
        plugin = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet"]},
            files={"skills/greet/SKILL.md": "greet\n", "README.md": "solo\n"},
        )
        first, second = self.destination("first"), self.destination("second")

        build.build(plugin, first)
        build.build(plugin, second)

        self.assertEqual(
            json.loads((first / LOCK_NAME).read_text())["contents"],
            json.loads((second / LOCK_NAME).read_text())["contents"],
        )
        self.assertEqual(files_under(first), files_under(second))
        differing = [
            path
            for path in sorted(files_under(first))
            if not filecmp.cmp(first / path, second / path, shallow=False)
        ]
        self.assertEqual(differing, [], f"two builds of one input differ: {differing}")

    def test_local_agent_settings_never_reach_the_folder_people_download(self):
        """`.claude` holds the author's machine, not the plugin.

        It sits outside every fingerprint, so the `contents` recorded in the
        lock file is the same number whether it was copied or not. That is what
        makes copying it dangerous rather than merely untidy: the record cannot
        show that it happened, so nothing downstream can notice the leak.
        """
        plugin = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet"]},
            files={
                "skills/greet/SKILL.md": "greet\n",
                ".claude/settings.local.json": '{"permissions": {"allow": ["Bash(secret)"]}}',
            },
        )
        out = self.destination()

        build.build(plugin, out)

        self.assertFalse(
            (out / ".claude").exists(),
            "the author's local settings shipped to whoever installs this",
        )
        self.assertIn(".claude", build.NEVER_SHIP)

    def test_the_cache_the_bootstrap_stub_writes_never_reaches_the_folder(self):
        """`.foundry` holds Foundry itself, fetched so this repo could be built.

        The stub writes it on the first build, so it is in every plugin
        repository that has ever run one. Copied through, each shipped folder
        carries Foundry's own source inside it, in a folder whose whole point is
        that nothing resolves where it is installed. It is in `SKIP_DIRS` too,
        so a plugin's pin does not depend on whether it has been built.
        """
        plugin = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet"]},
            files={
                "skills/greet/SKILL.md": "greet\n",
                ".foundry/0.1.0/VERSION": "0.1.0\n",
                ".foundry/0.1.0/scripts/build.py": "# a whole copy of Foundry\n",
            },
        )
        out = self.destination()

        build.build(plugin, out)

        self.assertFalse((out / ".foundry").exists(), "Foundry itself shipped inside the folder")
        self.assertIn(".foundry", build.NEVER_SHIP)
        self.assertIn(".foundry", resolve.SKIP_DIRS)

    def test_a_repo_built_once_fingerprints_the_same_as_one_never_built(self):
        """A pin has to mean the same thing on a machine that has built before.

        The cache is the difference between those two states and nothing else,
        so if it counted, the same source would pin differently everywhere and
        the instruction to pin against a clean checkout would describe a state
        no built repository can get back to.
        """
        never_built = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet"]},
            files={"skills/greet/SKILL.md": "greet\n"},
        )
        built_before = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet"]},
            files={
                "skills/greet/SKILL.md": "greet\n",
                ".foundry/0.1.0/VERSION": "0.1.0\n",
            },
        )

        self.assertEqual(
            resolve.fingerprint(never_built),
            resolve.fingerprint(built_before),
            "building a repository once changed what its pin means",
        )

    def test_an_earlier_release_is_not_copied_into_the_next_one(self):
        """`--out dist` twice is the first command the template's README gives.

        Without this the second run copies the whole of the first run's release
        into the new one, and the third copies the second's copy of the first.
        The output is matched by resolved path and not by the name `dist`,
        because the name is a convention and the flag takes anything.
        """
        plugin = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet"]},
            files={"skills/greet/SKILL.md": "greet\n"},
        )
        out = plugin / "dist"

        build.build(plugin, out)
        build.build(plugin, out)

        self.assertFalse((out / "dist").exists(), "the previous release shipped inside this one")
        self.assertTrue((out / "skills/greet/SKILL.md").is_file())

    def test_a_placeholder_holding_an_empty_directory_open_does_not_ship(self):
        """`.gitkeep` is git's business, and the shipped folder is not a git repo.

        The Foundry template holds `skills/`, `agents/`, `commands/` and
        `tests/` open with placeholders so a fresh plugin repository has
        somewhere to put its first skill. Copied through, each one is a file no
        harness reads sitting inside that folder's `contents` fingerprint, and
        an empty `agents/` claims a surface the plugin does not have.
        """
        plugin = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet"]},
            files={
                "skills/greet/SKILL.md": "greet\n",
                "skills/.gitkeep": "",
                "agents/.gitkeep": "",
                "commands/.gitkeep": "",
            },
        )
        out = self.destination()

        build.build(plugin, out)

        self.assertFalse((out / "skills/.gitkeep").exists(), "a placeholder shipped")
        self.assertFalse((out / "agents").exists(), "an empty agents/ shipped")
        self.assertFalse((out / "commands").exists(), "an empty commands/ shipped")
        self.assertTrue(
            (out / "skills/greet/SKILL.md").is_file(),
            "sweeping the placeholder took the real skill with it",
        )

    def test_a_dot_file_inside_a_skill_is_that_skills_own_business(self):
        """The sweep is one level deep, so it cannot reach into a skill.

        A skill directory is content the author wrote. Sweeping dot files out of
        it would silently edit somebody's skill on the way to the folder people
        install, which is the one thing an emitter is never allowed to do.
        """
        plugin = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet"]},
            files={
                "skills/greet/SKILL.md": "greet\n",
                "skills/greet/.assets": "kept\n",
            },
        )
        out = self.destination()

        build.build(plugin, out)

        self.assertTrue((out / "skills/greet/.assets").is_file(), "a file inside a skill was deleted")


class TakingFromADependency(RepoCase):
    def test_a_skill_taken_from_a_dependency_lands_in_the_output(self):
        dependency = make_repo(
            self.workspace,
            "library",
            files={
                "skills/audit/SKILL.md": "audit the thing\n",
                "skills/unwanted/SKILL.md": "not asked for\n",
                "README.md": "library\n",
            },
        )
        plugin = make_repo(
            self.workspace,
            "consumer",
            provides={"skills": ["audit"]},
            requires=[needs(dependency, take={"skills": ["audit"]})],
        )
        out = self.destination()

        build.build(plugin, out)

        self.assertEqual((out / "skills/audit/SKILL.md").read_text(), "audit the thing\n")
        shipped = files_under(out)
        self.assertNotIn("skills/unwanted/SKILL.md", shipped, "took more than it asked for")
        self.assertNotIn("README.md", shipped, "a dependency wrote outside its handed-over items")

    def test_two_dependencies_handing_over_one_name_stops_and_names_both(self):
        left = make_repo(self.workspace, "left", files={"skills/audit/SKILL.md": "left audit\n"})
        right = make_repo(self.workspace, "right", files={"skills/audit/SKILL.md": "right audit\n"})
        plugin = make_repo(
            self.workspace,
            "consumer",
            requires=[
                needs(left, take={"skills": ["audit"]}),
                needs(right, take={"skills": ["audit"]}),
            ],
        )

        with self.assertRaises(build.BuildError) as refusal:
            build.build(plugin, self.destination())

        message = str(refusal.exception)
        self.assertIn("TWO SOURCES FOR THE SAME THING", message)
        self.assertIn("skills/audit", message)
        self.assertIn("left", message)
        self.assertIn("right", message)

    def test_a_plugin_and_a_dependency_claiming_one_name_stops_and_names_both(self):
        """The plugin's own content is written first, so it is the other side here."""
        library = make_repo(self.workspace, "library", files={"skills/audit/SKILL.md": "library audit\n"})
        plugin = make_repo(
            self.workspace,
            "consumer",
            files={"skills/audit/SKILL.md": "the plugin's own audit\n"},
            requires=[needs(library, take={"skills": ["audit"]})],
        )

        with self.assertRaises(build.BuildError) as refusal:
            build.build(plugin, self.destination())

        message = str(refusal.exception)
        self.assertIn("TWO SOURCES FOR THE SAME THING", message)
        self.assertIn("skills/audit", message)
        self.assertIn("consumer", message)
        self.assertIn("library", message)

    def test_a_dependency_never_quietly_overwrites_a_file_the_plugin_already_wrote(self):
        """A single file collides by being copied over, which loses the original."""
        library = make_repo(self.workspace, "library", files={"commands/ship.md": "the library's ship\n"})
        plugin = make_repo(
            self.workspace,
            "consumer",
            files={"commands/ship.md": "the plugin's own ship\n"},
            requires=[needs(library, take={"commands": ["ship.md"]})],
        )
        out = self.destination()

        with self.assertRaises(build.BuildError) as refusal:
            build.build(plugin, out)

        message = str(refusal.exception)
        self.assertIn("TWO SOURCES FOR THE SAME THING", message)
        self.assertIn("commands/ship.md", message)


class ARefusedBuildLeavesNothingBehind(RepoCase):
    """The refusal fires partway through, after some of the folder is written.

    If that half-written folder survived, the guard on the next build would call
    it "not built by this tool" and tell the caller to point somewhere else,
    which is false and is not the fix. So the test is that the same output
    folder builds cleanly once the cause is removed.
    """

    def colliding_plugin(self) -> tuple:
        library = make_repo(self.workspace, "library", files={"commands/ship.md": "the library's ship\n"})
        plugin = make_repo(
            self.workspace,
            "consumer",
            files={"commands/ship.md": "the plugin's own ship\n"},
            requires=[needs(library, take={"commands": ["ship.md"]})],
        )
        return library, plugin

    def test_a_refused_build_writes_no_output_folder_and_no_scratch_beside_it(self):
        _, plugin = self.colliding_plugin()
        out = self.destination()

        with self.assertRaises(build.BuildError):
            build.build(plugin, out)

        self.assertFalse(out.exists(), "a refused build left a half-written folder on disk")
        self.assertEqual(
            sorted(entry.name for entry in out.parent.iterdir()),
            [],
            "a refused build left scratch beside the output folder",
        )

    def test_a_build_that_fails_then_succeeds_into_the_same_out_actually_succeeds(self):
        library, plugin = self.colliding_plugin()
        out = self.destination()

        with self.assertRaises(build.BuildError):
            build.build(plugin, out)

        # Stop taking the colliding command. Nothing else changes, least of all --out.
        make_repo(
            self.workspace,
            "consumer",
            files={"commands/ship.md": "the plugin's own ship\n"},
            requires=[needs(library)],
        )

        build.build(plugin, out)

        self.assertEqual((out / "commands/ship.md").read_text(), "the plugin's own ship\n")
        self.assertIn(LOCK_NAME, files_under(out))


class OnlyFourKindsCrossTheLine(RepoCase):
    """skills, agents, commands and hooks, and nothing else, either way.

    This is the only thing stopping a dependency writing wherever it likes in
    the shipped folder, and the only thing stopping a plugin claiming to provide
    something that is not plugin content. Widen the set of directories and both
    refusals disappear, so both are gated here.
    """

    KINDS = ("skills", "agents", "commands", "hooks")

    def test_taking_a_directory_that_is_not_plugin_content_is_refused(self):
        library = make_repo(self.workspace, "library", files={"scripts/foundry.py": "the stub\n"})
        plugin = make_repo(
            self.workspace,
            "consumer",
            requires=[needs(library, take={"scripts": ["foundry.py"]})],
        )

        with self.assertRaises(build.BuildError) as refusal:
            build.build(plugin, self.destination())

        message = str(refusal.exception)
        self.assertIn("cannot take 'scripts'", message)
        self.assertIn("library", message)
        for kind in self.KINDS:
            self.assertIn(kind, message, "the refusal does not name what may be handed over")

    def test_providing_a_directory_that_is_not_plugin_content_is_refused(self):
        plugin = make_repo(
            self.workspace,
            "consumer",
            provides={"scripts": ["foundry.py"]},
            files={"scripts/foundry.py": "the stub\n"},
        )

        with self.assertRaises(build.BuildError) as refusal:
            build.build(plugin, self.destination())

        message = str(refusal.exception)
        self.assertIn("'provides' lists 'scripts'", message)
        for kind in self.KINDS:
            self.assertIn(kind, message, "the refusal does not name what may be provided")


class ClaimsAreChecked(RepoCase):
    def test_claiming_something_absent_from_the_output_stops_and_names_it(self):
        plugin = make_repo(
            self.workspace,
            "solo",
            provides={"skills": ["greet", "ghost"]},
            files={"skills/greet/SKILL.md": "greet\n"},
        )

        with self.assertRaises(build.BuildError) as refusal:
            build.build(plugin, self.destination())

        message = str(refusal.exception)
        self.assertIn("CLAIMS SOMETHING IT DOES NOT HAVE", message)
        self.assertIn("skills/ghost", message)
        self.assertNotIn("skills/greet", message, "named something that is actually there")
