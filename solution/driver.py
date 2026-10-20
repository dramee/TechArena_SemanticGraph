import sys, os, time, json, collections
sys.setrecursionlimit(20000)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import Project
from interp import Interp, Trace
from repo import Repos
from web import Web, entry_request
import db as dbm
from values import *

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(root=ROOT):
    proj = Project(os.path.join(root, "skeleton/trainticket.json.gz"), os.path.join(root, "targets/trainticket"))
    tables = dbm.parse_dump(os.path.join(root, "context/db-after-warmup.sql.gz"))
    it = Interp(proj, tables)
    Repos(it)
    Web(it)
    return proj, it
