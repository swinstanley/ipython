# coding: utf-8
"""Test the notebooks webservice API."""

import io
import os
import shutil
from unicodedata import normalize

from zmq.utils import jsonapi

pjoin = os.path.join

import requests

from IPython.html.utils import url_path_join
from IPython.html.tests.launchnotebook import NotebookTestBase, assert_http_error
from IPython.nbformat.current import (new_notebook, write, read, new_worksheet,
                                      new_heading_cell, to_notebook_json)
from IPython.utils import py3compat
from IPython.utils.data import uniq_stable


class NBAPI(object):
    """Wrapper for notebook API calls."""
    def __init__(self, base_url):
        self.base_url = base_url

    def _req(self, verb, path, body=None, params=None):
        response = requests.request(verb,
                url_path_join(self.base_url, 'api/notebooks', path),
                data=body,
                params=params,
        )
        response.raise_for_status()
        return response

    def list(self, path='/'):
        return self._req('GET', path)

    def read(self, name, path='/'):
        return self._req('GET', url_path_join(path, name))

    def create_untitled(self, path='/'):
        return self._req('POST', path)

    def upload_untitled(self, body, path='/'):
        return self._req('POST', path, body)

    def copy_untitled(self, copy_from, path='/'):
        return self._req('POST', path, params={'copy':copy_from})

    def create(self, name, path='/'):
        return self._req('PUT', url_path_join(path, name))

    def upload(self, name, body, path='/'):
        return self._req('PUT', url_path_join(path, name), body)

    def copy(self, copy_from, copy_to, path='/'):
        return self._req('PUT', url_path_join(path, copy_to), params={'copy':copy_from})

    def save(self, name, body, path='/'):
        return self._req('PUT', url_path_join(path, name), body)

    def delete(self, name, path='/'):
        return self._req('DELETE', url_path_join(path, name))

    def rename(self, name, path, new_name):
        body = jsonapi.dumps({'name': new_name})
        return self._req('PATCH', url_path_join(path, name), body)

    def get_checkpoints(self, name, path):
        return self._req('GET', url_path_join(path, name, 'checkpoints'))

    def new_checkpoint(self, name, path):
        return self._req('POST', url_path_join(path, name, 'checkpoints'))

    def restore_checkpoint(self, name, path, checkpoint_id):
        return self._req('POST', url_path_join(path, name, 'checkpoints', checkpoint_id))

    def delete_checkpoint(self, name, path, checkpoint_id):
        return self._req('DELETE', url_path_join(path, name, 'checkpoints', checkpoint_id))

class APITest(NotebookTestBase):
    """Test the kernels web service API"""
    dirs_nbs = [('', 'inroot'),
                ('Directory with spaces in', 'inspace'),
                (u'unicodé', 'innonascii'),
                ('foo', 'a'),
                ('foo', 'b'),
                ('foo', 'name with spaces'),
                ('foo', u'unicodé'),
                ('foo/bar', 'baz'),
                (u'å b', u'ç d')
               ]

    dirs = uniq_stable([d for (d,n) in dirs_nbs])
    del dirs[0]  # remove ''

    def setUp(self):
        nbdir = self.notebook_dir.name

        for d in self.dirs:
            if not os.path.isdir(pjoin(nbdir, d)):
                os.mkdir(pjoin(nbdir, d))

        for d, name in self.dirs_nbs:
            with io.open(pjoin(nbdir, d, '%s.ipynb' % name), 'w') as f:
                nb = new_notebook(name=name)
                write(nb, f, format='ipynb')

        self.nb_api = NBAPI(self.base_url())

    def tearDown(self):
        nbdir = self.notebook_dir.name

        for dname in ['foo', 'Directory with spaces in', u'unicodé', u'å b']:
            shutil.rmtree(pjoin(nbdir, dname), ignore_errors=True)

        if os.path.isfile(pjoin(nbdir, 'inroot.ipynb')):
            os.unlink(pjoin(nbdir, 'inroot.ipynb'))

    def test_list_notebooks(self):
        nbs = self.nb_api.list().json()
        self.assertEqual(len(nbs), 1)
        self.assertEqual(nbs[0]['name'], 'inroot.ipynb')

        nbs = self.nb_api.list('/Directory with spaces in/').json()
        self.assertEqual(len(nbs), 1)
        self.assertEqual(nbs[0]['name'], 'inspace.ipynb')

        nbs = self.nb_api.list(u'/unicodé/').json()
        self.assertEqual(len(nbs), 1)
        self.assertEqual(nbs[0]['name'], 'innonascii.ipynb')
        self.assertEqual(nbs[0]['path'], u'unicodé')

        nbs = self.nb_api.list('/foo/bar/').json()
        self.assertEqual(len(nbs), 1)
        self.assertEqual(nbs[0]['name'], 'baz.ipynb')
        self.assertEqual(nbs[0]['path'], 'foo/bar')

        nbs = self.nb_api.list('foo').json()
        self.assertEqual(len(nbs), 4)
        nbnames = { normalize('NFC', n['name']) for n in nbs }
        expected = [ u'a.ipynb', u'b.ipynb', u'name with spaces.ipynb', u'unicodé.ipynb']
        expected = { normalize('NFC', name) for name in expected }
        self.assertEqual(nbnames, expected)

    def test_list_nonexistant_dir(self):
        with assert_http_error(404):
            self.nb_api.list('nonexistant')

    def test_get_contents(self):
        for d, name in self.dirs_nbs:
            nb = self.nb_api.read('%s.ipynb' % name, d+'/').json()
            self.assertEqual(nb['name'], u'%s.ipynb' % name)
            self.assertIn('content', nb)
            self.assertIn('metadata', nb['content'])
            self.assertIsInstance(nb['content']['metadata'], dict)

        # Name that doesn't exist - should be a 404
        with assert_http_error(404):
            self.nb_api.read('q.ipynb', 'foo')

    def _check_nb_created(self, resp, name, path):
        self.assertEqual(resp.status_code, 201)
        location_header = py3compat.str_to_unicode(resp.headers['Location'])
        self.assertEqual(location_header.split('/')[-1], name)
        self.assertEqual(resp.json()['name'], name)
        assert os.path.isfile(pjoin(self.notebook_dir.name, path, name))

    def test_create_untitled(self):
        resp = self.nb_api.create_untitled(path=u'å b')
        self._check_nb_created(resp, 'Untitled0.ipynb', u'å b')

        # Second time
        resp = self.nb_api.create_untitled(path=u'å b')
        self._check_nb_created(resp, 'Untitled1.ipynb', u'å b')

        # And two directories down
        resp = self.nb_api.create_untitled(path='foo/bar')
        self._check_nb_created(resp, 'Untitled0.ipynb', pjoin('foo', 'bar'))

    def test_upload_untitled(self):
        nb = new_notebook(name='Upload test')
        nbmodel = {'content': nb}
        resp = self.nb_api.upload_untitled(path=u'å b',
                                              body=jsonapi.dumps(nbmodel))
        self._check_nb_created(resp, 'Untitled0.ipynb', 'å b')

    def test_upload(self):
        nb = new_notebook(name=u'ignored')
        nbmodel = {'content': nb}
        resp = self.nb_api.upload(u'Upload tést.ipynb', path=u'å b',
                                              body=jsonapi.dumps(nbmodel))
        self._check_nb_created(resp, u'Upload tést.ipynb', u'å b')

    def test_copy_untitled(self):
        resp = self.nb_api.copy_untitled(u'ç d.ipynb', path=u'å b')
        self._check_nb_created(resp, u'ç d-Copy0.ipynb', u'å b')

    def test_copy(self):
        resp = self.nb_api.copy(u'ç d.ipynb', u'cøpy.ipynb', path=u'å b')
        self._check_nb_created(resp, u'cøpy.ipynb', u'å b')

    def test_delete(self):
        for d, name in self.dirs_nbs:
            resp = self.nb_api.delete('%s.ipynb' % name, d)
            self.assertEqual(resp.status_code, 204)

        for d in self.dirs + ['/']:
            nbs = self.nb_api.list(d).json()
            self.assertEqual(len(nbs), 0)

    def test_rename(self):
        resp = self.nb_api.rename('a.ipynb', 'foo', 'z.ipynb')
        self.assertEqual(resp.headers['Location'].split('/')[-1], 'z.ipynb')
        self.assertEqual(resp.json()['name'], 'z.ipynb')
        assert os.path.isfile(pjoin(self.notebook_dir.name, 'foo', 'z.ipynb'))

        nbs = self.nb_api.list('foo').json()
        nbnames = set(n['name'] for n in nbs)
        self.assertIn('z.ipynb', nbnames)
        self.assertNotIn('a.ipynb', nbnames)

    def test_save(self):
        resp = self.nb_api.read('a.ipynb', 'foo')
        nbcontent = jsonapi.loads(resp.text)['content']
        nb = to_notebook_json(nbcontent)
        ws = new_worksheet()
        nb.worksheets = [ws]
        ws.cells.append(new_heading_cell(u'Created by test ³'))

        nbmodel= {'name': 'a.ipynb', 'path':'foo', 'content': nb}
        resp = self.nb_api.save('a.ipynb', path='foo', body=jsonapi.dumps(nbmodel))

        nbfile = pjoin(self.notebook_dir.name, 'foo', 'a.ipynb')
        with io.open(nbfile, 'r', encoding='utf-8') as f:
            newnb = read(f, format='ipynb')
        self.assertEqual(newnb.worksheets[0].cells[0].source,
                         u'Created by test ³')
        nbcontent = self.nb_api.read('a.ipynb', 'foo').json()['content']
        newnb = to_notebook_json(nbcontent)
        self.assertEqual(newnb.worksheets[0].cells[0].source,
                         u'Created by test ³')

        # Save and rename
        nbmodel= {'name': 'a2.ipynb', 'path':'foo/bar', 'content': nb}
        resp = self.nb_api.save('a.ipynb', path='foo', body=jsonapi.dumps(nbmodel))
        saved = resp.json()
        self.assertEqual(saved['name'], 'a2.ipynb')
        self.assertEqual(saved['path'], 'foo/bar')
        assert os.path.isfile(pjoin(self.notebook_dir.name,'foo','bar','a2.ipynb'))
        assert not os.path.isfile(pjoin(self.notebook_dir.name, 'foo', 'a.ipynb'))
        with assert_http_error(404):
            self.nb_api.read('a.ipynb', 'foo')

    def test_checkpoints(self):
        resp = self.nb_api.read('a.ipynb', 'foo')
        r = self.nb_api.new_checkpoint('a.ipynb', 'foo')
        self.assertEqual(r.status_code, 201)
        cp1 = r.json()
        self.assertEqual(set(cp1), {'id', 'last_modified'})
        self.assertEqual(r.headers['Location'].split('/')[-1], cp1['id'])

        # Modify it
        nbcontent = jsonapi.loads(resp.text)['content']
        nb = to_notebook_json(nbcontent)
        ws = new_worksheet()
        nb.worksheets = [ws]
        hcell = new_heading_cell('Created by test')
        ws.cells.append(hcell)
        # Save
        nbmodel= {'name': 'a.ipynb', 'path':'foo', 'content': nb}
        resp = self.nb_api.save('a.ipynb', path='foo', body=jsonapi.dumps(nbmodel))

        # List checkpoints
        cps = self.nb_api.get_checkpoints('a.ipynb', 'foo').json()
        self.assertEqual(cps, [cp1])

        nbcontent = self.nb_api.read('a.ipynb', 'foo').json()['content']
        nb = to_notebook_json(nbcontent)
        self.assertEqual(nb.worksheets[0].cells[0].source, 'Created by test')

        # Restore cp1
        r = self.nb_api.restore_checkpoint('a.ipynb', 'foo', cp1['id'])
        self.assertEqual(r.status_code, 204)
        nbcontent = self.nb_api.read('a.ipynb', 'foo').json()['content']
        nb = to_notebook_json(nbcontent)
        self.assertEqual(nb.worksheets, [])

        # Delete cp1
        r = self.nb_api.delete_checkpoint('a.ipynb', 'foo', cp1['id'])
        self.assertEqual(r.status_code, 204)
        cps = self.nb_api.get_checkpoints('a.ipynb', 'foo').json()
        self.assertEqual(cps, [])
