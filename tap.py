#!/usr/bin/python
#
# Copyright 2011 Mark Nevill
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import apt_pkg
import apt

class InvalidOption(Exception):
    def __init__(self, *args, **kwargs):
        super(InvalidOption, self).__init__(*args, **kwargs)

#
# search "AST"
#

def namever_key(item):
    return item[0], item[1].package.name, item[1].version

class AndCombiner(object):
    def __init__(self, left, right):
        self.left, self.right = left, right

    def match(self, package):
        results = self.left.match(package)
        if not results:
            return []
        return self.right.filter(results)

    def filter(self, results):
        results = self.left.filter(results)
        if not results:
            return []
        return self.right.filter(results)

    def __repr__(self):
        return "%s(%r, %r)" % (self.__class__.__name__, self.left, self.right)

class OrCombiner(object):
    def __init__(self, left, right):
        self.left, self.right = left, right

    def _combine(self, left, right):
        merged = sorted(left+right, key=namever_key)
        # filter out duplicates
        keys = [namever_key(p) for p in merged]
        return [merged[i] for i in range(len(merged))
                if i == 0 or keys[i] != keys[i-1]]

    def match(self, package):
        left = self.left.match(package)
        right = self.right.match(package)
        return self._combine(left, right)

    def filter(self, results):
        left = self.left.filter(results)
        right = self.right.filter(results)
        return self._combine(left, right)

    def __repr__(self):
        return "%s(%r, %r)" % (self.__class__.__name__, self.left, self.right)

class Contains(object):
    def __init__(self, search):
        self.search = search
    def __call__(self, target):
        return self.search in target
    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.search)

class ContainsNoCase(object):
    def __init__(self, search):
        self.search = search.lower()
    def __call__(self, target):
        return self.search in target.lower()
    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.search)

class ContainsRegex(object):
    def __init__(self, pattern):
        if not hasattr(pattern, 'search'):
            import re
            pattern = re.compile(pattern)
        self.pattern = pattern
    def __call__(self, target):
        return bool(self.pattern.search(target))
    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.pattern)

class MatchName(object):
    def __init__(self, matcher):
        self.matcher = matcher

    def match(self, package):
        results = []
        for v in package.versions:
            results.extend(
                (provides, v)
                for provides in v.provides
                if self.matcher(provides)
            )
        if self.matcher(package.name):
            results.extend((package.name, v) for v in package.versions)
        return sorted(results, key=namever_key)

    def filter(self, results):
        return [
            result for result in results
            if self.matcher(result[0])
        ]

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.matcher)

class MatchDesc(object):
    def __init__(self, matcher):
        self.matcher = matcher

    def match(self, package):
        results = []
        for v in package.versions:
            if self.matcher(v._translated_records.long_desc):
                results.extend((provides, v) for provides in v.provides)
                results.append((package.name, v))
        return sorted(results, key=namever_key)

    def filter(self, results):
        return [
            result for result in results
            if self.matcher(result[1]._translated_records.long_desc)
        ]

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.matcher)

class Installed(object):
    def __init__(self):
        pass

    def match(self, package):
        if package.installed:
            return [(package.name, package.installed)]
        else:
            return []

    def filter(self, results):
        return [
            result for result in results
            if (result[1].package.name == result[0] and
                result[1].package.installed == result[1])
        ]

    def __repr__(self):
        return "%s()" % (self.__class__.__name__,)

class Nonvirtual(object):
    def __init__(self):
        pass

    def match(self, package):
        return [(package.name, v) for v in package.versions]

    def filter(self, results):
        return [r for r in results if r[0] == r[1].package.name]

    def __repr__(self):
        return "%s()" % (self.__class__.__name__,)

class MatchArch(object):
    def __init__(self, arch=None):
        if not arch:
            self.arch = [apt_pkg.config.find("APT::Architecture"), 'all']
        elif isinstance(arch, str):
            self.arch = [arch]
        else:
            self.arch = arch

    def match(self, package):
        results = []
        for v in package.versions:
            if v.architecture not in self.arch:
                continue
            results.extend((provides, v) for provides in v.provides)
            results.append((package.name, v))
        return results

    def filter(self, results):
        return [
            result for result in results
            if result[1].architecture in self.arch
        ]

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.arch)

#
# command handling
#

def search(config, args):

    def make_search(arg):
        conds = []
        has_arch = False
        while arg:

            if arg[0] == '~':
                op = arg[1]
                rem = arg[2:]
            else:
                op = 'n'
                rem = arg

            if op in 'nda':
                nextop = rem.find('~')
                if nextop != -1:
                    rem, arg = rem[:nextop], rem[nextop:]
                else:
                    arg = ""
            else:
                rem, arg = "", rem

            if op == 'a':
                has_arch = True
                if rem == 'any':
                    # skip constraint so all archs are matched
                    continue

            op = {
                'n': lambda r: MatchName(Contains(r)),
                'd': lambda r: MatchDesc(ContainsNoCase(r)),
                'i': lambda r: Installed(),
                'a': lambda r: MatchArch(r),
                'p': lambda r: Nonvirtual(),
            }[op]
            op = op(rem)

            conds.append(op)

        if conds and not has_arch:
            conds.append(MatchArch(None))

        if not conds:
            return lambda pkg: []
        elif len(conds) == 1:
            return conds[0]
        else:
            cond, conds = conds[-1], conds[:-1]
            while conds:
                cond = AndCombiner(conds.pop(), cond)
            return cond

    conds = []
    for arg in args:
        conds.append(make_search(arg))

    if not conds:
        cond = None
    elif len(conds) == 1:
        cond = conds[0]
    else:
        cond, conds = conds[-1], conds[:-1]
        while conds:
            cond = OrCombiner(conds.pop(), cond)

    print cond

    results = []
    if cond:
        cache = apt.Cache()
        results = [cond.match(p) for p in cache]
        import itertools
        results = sorted(
            itertools.chain(*results),
            key=namever_key
        )

    if not results:
        print "No results for search"
        return 1

    namelen = max(len(r[0]) for r in results)
    verlen = max(len(r[1].version) for r in results)
    default_format =  ('%%(state)s%%(automatic)s%%(upgrade)s'
                       ' %%(arch)-6s'
                       ' %%(name)-%(namelen)ds'
                       ' %%(version)-%(verlen)ds'
                       ' - %%(summary)s')
    default_vformat = ('%%(state)s%%(automatic)s%%(upgrade)s'
                       ' %%(arch)-6s'
                       ' %%(name)-%(namelen)ds'
                       ' ->'
                       ' %%(packagename)s'
                       ' %%(version)s')

    format = config.get('format', default_format)
    vformat = config.get('vformat', default_vformat)
    format = format % dict(namelen=namelen, verlen=verlen)
    vformat = vformat % dict(namelen=namelen, verlen=verlen)

    for name, version in results:
        package = version.package
        virtual = package.name != name
        installed = False

        if virtual:
            state = 'v'
        elif package.installed == version:
            installed = True
            if package.is_now_broken:
                state = 'b'
            else:
                state = {
                    apt_pkg.CURSTATE_CONFIG_FILES: 'c',
                    apt_pkg.CURSTATE_HALF_CONFIGURED: 'C',
                    apt_pkg.CURSTATE_HALF_INSTALLED: 'I',
                    apt_pkg.CURSTATE_UNPACKED: 'z',
                    apt_pkg.CURSTATE_INSTALLED: 'i',
                }.get(package._pkg.current_state, '?')
        elif package.installed is None and package.candidate == version:
            installed = True
            state = {
                apt_pkg.CURSTATE_CONFIG_FILES: 'c',
                apt_pkg.CURSTATE_HALF_CONFIGURED: 'C',
                apt_pkg.CURSTATE_HALF_INSTALLED: 'I',
                apt_pkg.CURSTATE_UNPACKED: 'z',
            }.get(package._pkg.current_state, 'p')
        else:
            state = 'p'

        automatic = ' '
        if installed:
            automatic = {
                (True, True): 'R',
                (True, False): 'A',
                (False, False): ' ',
                (False, True): '?',
            }[(package.is_auto_installed, package.is_auto_removable)]

        select = ' '
        if ((package.installed and package.installed == version) or
            (not package.installed and package.candidate == version)):
            select = {
                apt_pkg.SELSTATE_INSTALL: 'i',
                apt_pkg.SELSTATE_DEINSTALL: 'd',
                apt_pkg.SELSTATE_HOLD: 'h',
                apt_pkg.SELSTATE_PURGE: 'p',
                apt_pkg.SELSTATE_UNKNOWN: '?',
            }.get(package._pkg.selected_state, ' ')

        upgrade = ' '
        if installed and package.is_upgradable:
            upgrade = 'u'

        lineformat = vformat if virtual else format
        print lineformat % dict(
            state=state,
            automatic=automatic,
            upgrade=upgrade,
            arch=version.architecture,
            name=name,
            packagename=package.name,
            version=version.version,
            summary=version.summary,
        )

def search_help(config, argv):
    print "search help"
    sys.exit(0)

def search_format(target, config, argv):
    if not argv:
        raise InvalidOption("format option requires format string argument")
    fmtarg = argv[0]
    format = ""
    while fmtarg:
        index = fmtarg.find('%')
        if index < 0:
            format += fmtarg
            break
        format, fmtarg = format+fmtarg[:index], fmtarg[index+1:]
        align = False
        if fmtarg[0] == '|':
            align = True
            fmtarg = fmtarg[1:]
        fmtchar, fmtarg = fmtarg[0], fmtarg[1:]

        if fmtchar == 'n':
            if align:
                format += '%%(name)-%(namelen)ds'
            else:
                format += '%%(name)s'
        elif fmtchar == 'v':
            if align:
                format += '%%(version)-%(verlen)ds'
            else:
                format += '%%(version)s'
        elif fmtchar == 'a':
            if align:
                format += '%%(arch)-6s'
            else:
                format += '%%(arch)s'
        elif fmtchar == 'p':
            format += '%%(packagename)s'
        elif fmtchar == 'd':
            format += '%%(summary)s'
        elif fmtchar == 's':
            format += '%%(state)s'
        elif fmtchar == 'A':
            format += '%%(automatic)s'
        elif fmtchar == 'u':
            format += '%%(upgrade)s'
        else:
            raise Exception("Unkown format character "+fmtchar)
    config[target] = format
    argv[:] = argv[1:]

import functools
search_options = {
    'h': search_help,
    'help': search_help,
    'F': functools.partial(search_format, 'format'),
    'format': functools.partial(search_format, 'format'),
    'G': functools.partial(search_format, 'vformat'),
    'vformat': functools.partial(search_format, 'vformat'),
    'virtual-format': functools.partial(search_format, 'vformat'),
}

#
# main
#

def print_help():
    print "global help"

def global_help(config, argv):
    print_help()
    sys.exit(0)

def more_verbosity(config, argv):
    config.setdefault('verbosity', 0)
    config['verbosity'] += 1

options = {
    'h': global_help,
    'help': global_help,
    'v': more_verbosity,
    'verbose': more_verbosity,
}

def main(argv):

    command = None
    command_options = {}
    config = {}
    args = []
    commands = {
        'search': (search, search_options)
    }

    # Remove this line if Tap starts supporting multiple commands
    command, command_options = commands["search"]

    while argv:
        arg = argv.pop(0)

        if arg.startswith("--"):
            long_opt = arg[2:]
            if len(long_opt) < 2:
                raise InvalidOption("Invalid long option %r" % arg)
            elif long_opt in command_options:
                command_options[long_opt](config, argv)
            elif long_opt in options:
                options[long_opt](config, argv)
            else:
                raise InvalidOption("Invalid long option %r" % arg)

        elif arg.startswith("-"):
            if len(arg[1:]) < 1:
                raise InvalidOption("Invalid short option %r" % arg)
            for short_opt in arg[1:-1]:
                if short_opt in command_options:
                    command_options[short_opt](config, [])
                elif short_opt in options:
                    options[short_opt](config, [])
                else:
                    raise InvalidOption("Invalid short option %r" % ('-'+short_opt))
            short_opt = arg[-1]
            if short_opt in command_options:
                command_options[short_opt](config, argv)
            elif short_opt in options:
                options[short_opt](config, argv)
            else:
                raise InvalidOption("Invalid short option %r" % ('-'+short_opt))

        elif command is None:
            if arg in commands:
                command, command_options = commands[arg]
            else:
                command, command_options = commands["search"]
                args.append(arg)

        else:
            args.append(arg)

    print (command.__name__ if command else command), config, args

    if not command:
        print_help()
        return 1
    else:
        import apt_pkg
        apt_pkg.init()
        return command(config, args) or 0

if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(127)
