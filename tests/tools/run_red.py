import sys, unittest, importlib, os
sys.path.insert(0, os.path.join(os.environ["TS_REPO"], "tests")); sys.path.insert(0, os.environ["TS_REPO"])


class R(unittest.TextTestResult):
    def _rec(self, st, t, extra=""):
        print("%-7s %s %s" % (st, t.id().split(".", 1)[-1] if "." in t.id() else t.id(), extra[:200].replace("\n", " ")))

    def addSuccess(self, t):
        super().addSuccess(t)
        self._rec("ok", t)

    def addFailure(self, t, e):
        super().addFailure(t, e)
        self._rec("FAIL", t, str(e[1]).splitlines()[0] if str(e[1]) else "")

    def addError(self, t, e):
        super().addError(t, e)
        self._rec("ERROR", t, repr(e[1]))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._rec("SUBFAIL", test, "%s :: %s" % (subtest._subDescription(), str(err[1]).splitlines()[0] if str(err[1]) else repr(err[1])))

    def addSkip(self, t, r):
        super().addSkip(t, r)
        self._rec("skip", t, r)


for name in sys.argv[1:]:
    m = importlib.import_module(name)
    suite = unittest.defaultTestLoader.loadTestsFromModule(m)
    res = unittest.TextTestRunner(stream=open(os.devnull, "w"), resultclass=R).run(suite)
    print("== %s: ran %d fail %d error %d skip %d" % (name, res.testsRun, len(res.failures), len(res.errors), len(res.skipped)))
