import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from ggf_auth_token import AuthManager
from ggf_catalog import fetch,Variants
from ggf_installer import discover_install_files
from ggf_packages import extract,PackageError
from ggf_runtime import urlopen_with_ssl,launch_console_command

class Reply(io.BytesIO):
    status=200
    def __init__(self,body=b'@echo off',n=None,name='tool.bat'):
        super().__init__(body);self.headers=Message()
        self.headers['Content-Length']=str(len(body) if n is None else n)
        self.headers['Content-Disposition']='attachment; filename="'+name+'"'

class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.base=Path(self.t.name)
    def test_archive_preflight_windows_aliases(self):
        for n,names in enumerate([['ok','CON.txt'],['x','X'],['data:stream'],['a/b','a'],['dir/../../escape'],
                                  ['a.','b'],['.ggf-install.json'],['ok','NUL'],['A','a/file']]):
            with self.subTest(names=names):
                archive=self.base/f'{n}.zip';out=self.base/f'o{n}'
                with zipfile.ZipFile(archive,'w') as z:
                    for name in names:z.writestr(name,'x')
                with self.assertRaises(PackageError):extract(archive,out)
                self.assertFalse(out.exists())
    def test_archive_links_disallowed_before_writes(self):
        zpath=self.base/'link.zip';i=zipfile.ZipInfo('shortcut');i.external_attr=(stat.S_IFLNK|0o777)<<16
        with zipfile.ZipFile(zpath,'w') as z:z.writestr('good','ok');z.writestr(i,'../victim')
        with self.assertRaises(PackageError):extract(zpath,self.base/'out')
        self.assertFalse((self.base/'out').exists())
    def test_ambiguous_and_bundled_programs(self):
        for name in ['install-cuda12.bat','install-cuda13.bat','aria2c.exe','unins001.exe','update.bat','venv/Scripts/python.exe']:
            path=self.base/name;path.parent.mkdir(exist_ok=True,parents=True);path.touch()
        found=discover_install_files(self.base)
        self.assertIsNone(found['best_installer']);self.assertIsNone(found['best_launcher']);self.assertFalse(found['executables'])
        child=self.base/'App';child.mkdir();(child/'Start.bat').touch()
        self.assertEqual(Path(discover_install_files(self.base)['best_launcher']),child/'Start.bat')
    def test_solo_manager_is_launchable(self):
        path=self.base/'Flux2-Model-Manager.bat';path.touch()
        self.assertEqual(Path(discover_install_files(self.base)['best_launcher']),path)
    def test_cmd_working_dir_handles_metacharacters(self):
        sub=self.base/'two & more (%PATH%)!';sub.mkdir()
        bat=sub/'run & test (%PATH%)!.cmd';bat.write_text('@echo off\ncd > "cwd.txt"\n')
        with patch('subprocess.CREATE_NEW_CONSOLE',0):
            proc=launch_console_command([bat],cwd=str(sub),keep_open=False)
            self.assertEqual(proc.wait(8),0)
        self.assertEqual((sub/'cwd.txt').read_text().strip(),str(sub))
    def test_bearer_not_in_browser_or_cache_plaintext(self):
        mgr=AuthManager(str(self.base/'account.dat'))
        with patch('webbrowser.open') as browser: token=mgr.login()
        url=browser.call_args.args[0]
        self.assertNotIn(token,url);self.assertIn(hashlib.sha256(token.encode()).hexdigest(),url)
        import time
        mgr.save_cache(dict(token=token,expires=time.time()+120,tier='free',name='Test'))
        self.assertNotIn(token.encode(),Path(mgr.cache_file).read_bytes())
        two=AuthManager(mgr.cache_file);self.assertEqual(two.cached_auth['token'],token)
        mgr.clear_cache();self.assertIsNone(two.get_auth())
    def test_no_credential_redirects_or_other_origins(self):
        req=urllib.request.Request('https://elsewhere.invalid/file',headers={'X-GGF-App-Token':'secret'})
        with self.assertRaises(ValueError):urlopen_with_ssl(req)
        req=urllib.request.Request('https://getgoingfast.pro/download-api.php',headers={'X-GGF-App-Token':'secret'})
        with patch('urllib.request.build_opener') as call:
            urlopen_with_ssl(req)
            handler=call.call_args.args[0];self.assertIsNone(handler.redirect_request(req,None,302,'',{},'https://elsewhere.invalid'))
    def test_member_download_and_atomic_name_collision(self):
        token='ggf_desktop_'+'Z'*43
        with patch('ggf_catalog.urlopen_with_ssl',side_effect=lambda *a,**k:Reply()) as opener:
            got=fetch('test',token,self.base,lambda *a:None); second=fetch('test',token,self.base,lambda *a:None)
        self.assertEqual(got.read_bytes(),second.read_bytes());self.assertNotEqual(got,second)
        req=opener.call_args.args[0]; self.assertNotIn(token,req.full_url);self.assertIn(token,dict(req.header_items()).values())
    def test_partial_or_cancelled_never_promoted(self):
        for name,reply,cancel in [('partial',Reply(n=99),False),('cancel',Reply(),True),('device',Reply(name='CON.exe'),False)]:
            with self.subTest(name=name),patch('ggf_catalog.urlopen_with_ssl',return_value=reply):
                with self.assertRaises((ValueError,InterruptedError,PackageError)):fetch('ok','ggf_desktop_'+'z'*43,self.base,lambda *a:None,lambda:cancel)
                self.assertFalse(list(self.base.iterdir()))

