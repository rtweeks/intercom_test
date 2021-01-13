_nominal_version = "2.1.0"

import os.path
import subprocess
import sys

class VersionInfo:
    version_unknown = False
    modified = False
    git_dir = os.path.join(os.path.dirname(__file__), "..", "..", ".git")
    
    def __init__(self, version):
        super().__init__()
        self._base_version = version
        self._compute_status()
    
    @property
    def base_version(self):
        return self._base_version
    
    @property
    def version_tag(self):
        return "v" + self.base_version
    
    def _compute_status(self, ):
        subp = subprocess
        if '+' not in self.base_version and self.git_dir and os.path.exists(self.git_dir):
            self.version_unknown = self.get_version_unknown()
            self.modified = self.get_modified_status()
        else:
            # Not in a git repo, so accept the version number
            pass
        
        if self.version_unknown:
            self.actual_version = self.base_version + "+Unreleased"
        elif self.modified:
            self.actual_version = self.base_version + "+LocalModifications"
        else:
            self.actual_version = self.base_version
    
    def get_modified_status(self):
        return self._git_cmd_for_vtag("diff --quiet", stderr=subprocess.DEVNULL)
    
    def get_version_unknown(self, ):
        return self._git_cmd_for_vtag("rev-parse --verify --quiet", stdout=subprocess.DEVNULL)
    
    def _git_cmd_for_vtag(self, cmd_str, *, subp='call', **kwargs):
        try:
            return getattr(subprocess, subp)(
                ["git"] + cmd_str.split() + [self.version_tag],
                **kwargs
            )
        except FileNotFoundError:
            return None

__version__ = VersionInfo(_nominal_version).actual_version
