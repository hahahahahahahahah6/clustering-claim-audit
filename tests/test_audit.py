import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from clustering_claim_audit.audit import audit, claims, evidence, main, normalize
from clustering_claim_audit.phrases import CLUSTERING, NOCLUSTERING


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                code = main(list(args))
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue()

    def test_counts_order_normalization(self):
        self.assertEqual(len(CLUSTERING), 63)
        self.assertEqual(len(NOCLUSTERING), 28)
        self.assertEqual(len(set(CLUSTERING)), 63)
        self.assertEqual(len(set(NOCLUSTERING)), 28)
        for phrase in CLUSTERING + NOCLUSTERING:
            self.assertEqual(phrase, normalize(phrase))
        self.assertEqual(claims("doesn't cluster data"), ([], ['does not cluster data']))
        self.assertEqual(claims('K-MEANS clustering'), (['k means clustering'], []))

    def test_span_removal(self):
        self.assertEqual(claims('does not cluster data'), ([], ['does not cluster data']))
        self.assertEqual(claims('no clustering support'), ([], ['no clustering support']))

    def test_fences_inline_paragraphs_boundaries(self):
        self.assertEqual(claims('```sh\nclusters data\n```\n~~~\nno clustering\n~~~'), ([], []))
        self.assertEqual(claims('   ````\nclusters data\n```\nno clustering\n````'), ([], []))
        self.assertEqual(claims('`clusters data`')[0], ['clusters data'])
        self.assertEqual(claims('clusters\n\ndata'), ([], []))
        self.assertEqual(claims('xclusters datax cluster clustering clusters'), ([], []))

    def test_scope(self):
        self.write('other.md', 'clusters data')
        self.write('nested/README.md', 'clusters data')
        self.assertEqual(audit(self.root)['status'], 'PASS')
        self.write('nested/docs/a.md', 'clusters data')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')
        self.assertEqual(audit(self.root, ['nested'])['status'], 'PASS')

    def test_source_exclusions_and_tests(self):
        self.write('README.md', 'clusters data')
        code = 'from sklearn.cluster import KMeans\nKMeans()'
        for folder in ('fixtures', 'docs', 'examples'):
            self.write(folder + '/a.py', code)
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')
        self.write('tests/a.py', code)
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')
        for name in ('test_a.py', 'a_test.py'):
            self.write(name, code)
        self.assertEqual(len(audit(self.root)['evidence']['tests']), 3)
        self.write('app.py', code)
        self.assertEqual(audit(self.root)['status'], 'PASS')

    def test_symlinks(self):
        target = self.write('fixtures/source.py', 'from hdbscan import HDBSCAN\nHDBSCAN()')
        (self.root/'linked.py').symlink_to(target)
        (self.root/'linked').symlink_to(target.parent, target_is_directory=True)
        self.assertEqual(audit(self.root)['evidence']['production'], [])

    def test_findings_cli(self):
        self.write('README.md', 'clusters data')
        code, out = self.cli(str(self.root), '--json')
        self.assertEqual(code, 2)
        result = json.loads(out)
        self.assertEqual([(f['rule'], f['severity']) for f in result['findings']], [('documented-clustering-claim-false', 'HIGH')])
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['verdict'], result['status'])
        self.assertTrue(isinstance(result['findings'][0]['message'], str) and result['findings'][0]['message'])
        self.write('tests/a.py', 'import hdbscan\nhdbscan.HDBSCAN()')
        self.assertEqual(self.cli(str(self.root))[0], 0)
        self.assertEqual(self.cli(str(self.root), '--fail-on', 'MEDIUM')[0], 2)
        self.assertIn('tests/a.py', self.cli(str(self.root), '--verbose')[1])
        self.assertEqual(self.cli(str(self.root), '--ignore', 'README.md')[0], 0)
        self.write('README.md', 'no clustering')
        self.assertEqual(audit(self.root)['status'], 'PASS')
        self.write('app.py', 'import hdbscan\nhdbscan.HDBSCAN()')
        result = audit(self.root)
        self.assertEqual([(f['rule'], f['severity']) for f in result['findings']], [('documented-no-clustering-claim-false', 'HIGH')])
        self.assertEqual(self.cli(str(self.root))[0], 2)

    def test_no_source_negative(self):
        self.write('README.md', 'no clustering')
        self.assertEqual(audit(self.root)['status'], 'PASS')

    def test_cli_errors_version(self):
        self.assertEqual(self.cli('--version'), (0, '0.1.0\n'))
        self.assertEqual(self.cli()[0], 1)
        self.assertEqual(self.cli('--unknown')[0], 1)
        self.assertEqual(self.cli(str(self.root), '--fail-on', 'WRONG')[0], 1)
        self.assertEqual(self.cli(str(self.root/'missing'))[0], 1)

    def test_self_audit(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(claims((root/'README.md').read_text()), ([], []))
        self.assertEqual(audit(root)['status'], 'PASS')


def add_case(name, callback):
    setattr(AuditTests, name, callback)

for index, phrase in enumerate(CLUSTERING):
    def check(self, phrase=phrase):
        self.assertEqual(claims(phrase), ([phrase], []))
    add_case('test_positive_phrase_%02d' % index, check)
for index, phrase in enumerate(NOCLUSTERING):
    def check(self, phrase=phrase):
        self.assertEqual(claims(phrase), ([], [phrase]))
    add_case('test_negative_phrase_%02d' % index, check)

routes = []
for name in ('KMeans', 'MiniBatchKMeans', 'DBSCAN', 'OPTICS', 'AgglomerativeClustering', 'Birch', 'SpectralClustering', 'AffinityPropagation', 'MeanShift'):
    routes.extend(['from sklearn.cluster import '+name+'\n'+name+'()',
                   'from sklearn.cluster import '+name+' as C\nC()',
                   'import sklearn.cluster\nsklearn.cluster.'+name+'()',
                   'from sklearn import cluster\ncluster.'+name+'()',
                   'import sklearn.cluster as cl\ncl.'+name+'()'])
for module, name in [('sklearn.mixture', 'GaussianMixture'), ('scipy.cluster.hierarchy', 'linkage'), ('scipy.cluster.hierarchy', 'fcluster'), ('hdbscan', 'HDBSCAN')]:
    routes.extend(['from '+module+' import '+name+'\n'+name+'()', 'from '+module+' import '+name+' as C\nC()', 'import '+module+'\n'+module+'.'+name+'()', 'import '+module+' as m\nm.'+name+'()'])
routes.extend(['from sklearn import mixture\nmixture.GaussianMixture()', 'from scipy.cluster import hierarchy\nhierarchy.linkage()', 'from sklearn.cluster import KMeans\nm = KMeans()\nm.fit_predict(X)', 'from sklearn.cluster import KMeans\nKMeans().fit_predict(X)'])
for index, source in enumerate(routes):
    def check(self, source=source):
        self.assertTrue(evidence(source), source)
    add_case('test_evidence_%02d' % index, check)

negative = [
 'from sklearn.neighbors import KNeighborsClassifier\nKNeighborsClassifier()',
 'from sklearn.neighbors import NearestNeighbors\nNearestNeighbors().kneighbors(X)',
 'from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor\nRandomForestClassifier()\nRandomForestRegressor()',
 'sorted(data)\ndata.sort()', 'df.groupby("key")', 'from itertools import groupby\ngroupby(data)',
 'd = {}\nfor x in data:\n d.setdefault(x.key, []).append(x)', 'sql = "SELECT k FROM t GROUP BY k"',
 'from sklearn.feature_extraction.text import TfidfVectorizer\nTfidfVectorizer()',
 'from sklearn.decomposition import PCA, TruncatedSVD\nPCA()\nTruncatedSVD()',
 'from sklearn.metrics import silhouette_score, davies_bouldin_score, calinski_harabasz_score\nsilhouette_score(X, y)\ndavies_bouldin_score(X,y)\ncalinski_harabasz_score(X,y)',
 'from sklearn.datasets import make_blobs, make_circles, load_iris\nmake_blobs()\nmake_circles()\nload_iris()',
 'from sklearn.decomposition import LatentDirichletAllocation, NMF\nLatentDirichletAllocation()\nNMF()',
 'from sklearn.cluster import KMeans', 'from sklearn.cluster import KMeans\nKMeans',
 's = "KMeans()"', 'import subprocess\nsubprocess.run(["KMeans()"])', 'model.fit(X)',
 'from sklearn.cluster import KMeans\ndef KMeans(): pass\nKMeans()',
 'from sklearn.cluster import KMeans\nclass KMeans: pass\nKMeans()',
 'import sklearn.cluster as cl\ncl = fake\ncl.KMeans()',
 'from scipy.cluster.hierarchy import linkage\ndef linkage(): pass\nlinkage()',
 'from hdbscan import HDBSCAN\nclass HDBSCAN: pass\nHDBSCAN()',
 'import sklearn.cluster\nthis is invalid syntax !!!']
for index, source in enumerate(negative):
    def check(self, source=source):
        self.assertFalse(evidence(source), source)
    add_case('test_rejection_%02d' % index, check)
