import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixture import GitRepo  # noqa: E402

BIG_LEGACY = "".join(f"export const V{i} = {i};\n" for i in range(40))


class ModuleLintTest(unittest.TestCase):
    def setUp(self):
        self.repo = GitRepo({
            "src/legacy.ts": BIG_LEGACY,
            "src/billing/index.ts": 'export { charge } from "./charge";\n',
            "src/billing/charge.ts": "export function charge() {\n  return 1;\n}\n",
            "src/routes/old.ts": 'import { charge } from "../billing/charge";\nexport const x = charge;\n',
            "pkg/__init__.py": "from ._impl import run\n",
            "pkg/_impl.py": "def run():\n    return 1\n",
            "src/billing/charge.test.ts": "".join(f"// line {i}\n" for i in range(80)),
        })

    def tearDown(self):
        self.repo.cleanup()

    def lint(self, *args):
        return self.repo.run("python3", "scripts/ai/module_lint.py", *args)

    def test_audit_mode_only_warns_on_legacy(self):
        res = self.lint()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("WARNING src/legacy.ts:1: legacy 40 lines", res.stdout)
        self.assertIn("legacy imports '../billing/charge'", res.stdout)
        self.assertNotIn("charge.test.ts", res.stdout)  # tests exempt

    def test_new_oversized_file_fails(self):
        self.repo.write("src/newbig.ts", BIG_LEGACY)
        self.repo.commit("new")
        res = self.lint("--base", self.repo.base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("ERROR   src/newbig.ts:1: new file", res.stdout)

    def test_new_deep_import_fails_index_import_passes(self):
        self.repo.write("src/routes/new.ts", 'import { charge } from "../billing";\nexport const y = charge;\n')
        self.repo.commit("good")
        self.assertEqual(self.lint("--base", self.repo.base).returncode, 0)
        self.repo.write("src/routes/new.ts", 'import { charge } from "../billing/charge.js";\nexport const y = charge;\n')
        self.repo.commit("bad")
        res = self.lint("--base", self.repo.base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("internal file of module 'src/billing'", res.stdout)

    def test_internal_imports_inside_module_are_fine(self):
        self.repo.write("src/billing/refund.ts", 'import { charge } from "./charge";\nexport const r = charge;\n')
        self.repo.commit("internal")
        self.assertEqual(self.lint("--base", self.repo.base).returncode, 0)

    def test_new_python_private_import_fails(self):
        self.repo.write("app/main.py", "from pkg._impl import run\n\nrun()\n")
        self.repo.commit("bad py")
        res = self.lint("--base", self.repo.base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("private module 'pkg._impl'", res.stdout)

    def test_alias_import_resolved_via_tsconfig(self):
        self.repo.write("tsconfig.json", '{ "compilerOptions": { "paths": { "@/*": ["./src/*"] } } }\n')
        self.repo.write("src/routes/alias.ts", 'import { charge } from "@/billing/charge";\nexport const z = charge;\n')
        self.repo.commit("alias")
        res = self.lint("--base", self.repo.base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("'@/billing/charge'", res.stdout)


if __name__ == "__main__":
    unittest.main()
