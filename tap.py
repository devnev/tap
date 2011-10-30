#!/usr/bin/python
import sys
import apt_pkg
import apt

#
# search
#

def namever_key(item):
    return item[0], item[1].package.name, item[1].version

def and_(l, r):
    def merge(p):
        left = l(p)
        if not left:
            return []
        right = r(p)
        if not right:
            return []
        merged = sorted(left+right, key=namever_key)
        results = [merged[i] for i in range(len(merged)-1)
                   if namever_key(merged[i]) == namever_key(merged[i+1])]
        return results
    return merge

def or_(l, r):
    def merge(p):
        left = l(p)
        right = r(p)
        merged = sorted(left+right, key=namever_key)
        results = [merged[i] for i in range(len(merged))
                   if i == 0 or namever_key(merged[i]) != namever_key(merged[i-1])]
        return results
    return merge

def match_name(f):
    def match(pkg):
        results = []
        for v in pkg.versions:
            for provides in v.provides:
                if f(provides):
                    results.append((provides, v))
        if f(pkg.name):
            results.extend((pkg.name, v) for v in pkg.versions)
        return sorted(results, key=namever_key)
    return match

def match_desc(f):
    def match(pkg):
        results = []
        for v in pkg.versions:
            if f(v._translated_records.long_desc):
                for provides in v.provides:
                    results.append((provides, v))
                results.append((pkg.name, v))
        return results
    return match

def match_installed():
    def match(pkg):
        if pkg.installed:
            return [(pkg.name, pkg.installed)]
        else:
            return []
    return match

def match_nonvirtual():
    def match(pkg):
        return [(pkg.name, v) for v in pkg.versions]
    return match

def match_arch(arch):
    if not arch:
        arch = [apt_pkg.config.find("APT::Architecture"), 'all']
    else:
        arch = [arch]
    def match(pkg):
        results = []
        for v in pkg.versions:
            if v.architecture not in arch:
                continue
            results.extend((provides, v) for provides in v.provides)
            results.append((pkg.name, v))
        return results
    return match

def search(opts, args):

    def make_search(arg):
        conds = []
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

            op = {
                'n': lambda r: match_name(lambda n: r in n),
                'd': lambda r: match_desc(lambda n: r.lower() in n.lower()),
                'i': lambda r: match_installed(),
                'a': lambda r: match_arch(r),
                'p': lambda r: match_nonvirtual(),
            }[op]
            op = op(rem)

            conds.append(op)

        if not conds:
            return lambda pkg: []
        elif len(conds) == 1:
            return conds[0]
        else:
            cond, conds = conds[-1], conds[:-1]
            while conds:
                cond = and_(conds.pop(), cond)
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
            cond = or_(conds.pop(), cond)

    results = []
    if cond:
        cache = apt.Cache()
        results = [cond(p) for p in cache]
        import itertools
        results = sorted(
            itertools.chain(*results),
            key=namever_key
        )

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

        if virtual:
            parts = [
                state,
                automatic,
                upgrade,
                ' %-6s ' % version.architecture,
                name,
                ' -> ',
                package.name,
                ' ',
                version.version,
            ]
        else:
            parts = [
                state,
                automatic,
                upgrade,
                ' %-6s ' % version.architecture,
                name,
                ' ',
                version.version,
            ]
        print ''.join(parts)

def search_help(config, argv):
    print "search help"
    sys.exit(0)

search_options = {
    'h': search_help,
    'help': search_help,
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

class InvalidOption(Exception):
    def __init__(self, *args, **kwargs):
        super(InvalidOption, self).__init__(*args, **kwargs)

def main(argv):

    command = None
    command_options = {}
    config = {}
    args = []
    commands = {
        'search': (search, search_options)
    }

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
