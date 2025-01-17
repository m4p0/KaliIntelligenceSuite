#!/usr/bin/env python3

"""
this script implements a commandline interface to collect intelligence. the collection is performed by so called
collectors.

a collector is a Python module, which can operate on the IPv4/IPv6 address (e.g., collector shodanhost), IPv4/IPv6 network
(e.g., collector tcpnmap), service (e.g., collector ftphydra), or second-level domain (e.g., collector theharvester)
level. the collectors create these commands based on the data that is available in the KIS database and after each
execution, they perform the following tasks:

  * analyse the OS command's output
  * report any potential valuable information to the user
  * enrich the data (e.g., newly identified IPv4/IPv6 addresses, host names, URLs, credentials, etc.) in the database to
  ensure that subsequent collectors can re-use it

collectors are executed in a specific order to ensure that information required by one collector (e.g., httpeyewitness)
is already collected by another (e.g., httpgobuster).

Note: service-level collectors identify services from which they can collect intelligence by comparing the protocol
(TCP or UDP) and port number or by the nmap service name. the nmap service name is useful, if services are running on
non-standard ports. at the moment, only the service names of nmap are supported, which means that only from
nmap scan results, KIS is able to collect intel from services running on non-standard ports
"""

__author__ = "Lukas Reiter"
__license__ = "GPL v3.0"
__copyright__ = """Copyright 2018 Lukas Reiter

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
__version__ = 0.1

import argparse
import sys
import queue
import traceback
import os
import logging
import tempfile
from database.config import SortingHelpFormatter
from database.config import BaseConfig
from database.config import Collector
from collectors.os.collector import CollectorProducer
from view.console import KisCollectConsole
from database.model import CommandStatus
from database.model import VhostChoice
from database.utils import Engine
from database.utils import DeclarativeBase


if __name__ == "__main__":
    try:
        engine = Engine()
        DeclarativeBase.metadata.bind = engine.engine
        commands_queue = queue.Queue()
        producer = CollectorProducer(engine, commands_queue)
        epilog='''---- USE CASES ----

- I. semi-passive subdomain gathering

conservatively collect information (e.g., subdomains, email addresses, IPv4/IPv6 addresses, or IPv4/IPv6 address 
ownerships) about second-level domains using whois, theharvester, sublist3r, etc.

before you  start: specify a workspace $ws (e.g., ws=osint), the list of public second-level domains $domains as well 
as their sub-domains $hostnames to investigate (e.g., domains=megacorpone.com and hostnames=www.megacorpone.com)

import domains into database and execute collection
$ docker exec -it kaliintelsuite kismanage workspace --add $ws
$ docker exec -it kaliintelsuite kismanage domain -w $ws --add $domains
$ docker exec -it kaliintelsuite kismanage hostname -w $ws --add $domains $hostnames
$ docker exec -it kaliintelsuite kiscollect -w $ws --debug --awsslurp --builtwith --censysdomain \
--certspotter --crtshdomain --dnsamasspassive --dnscrobatdomain --dnscrobattld --dnsdumpster --dnshostpublic \
--dnsspf --dnssublist3r --haveibeenbreach --haveibeenpaste --hostio --hunter --securitytrails --theharvester \
--virustotal --whoisdomain --whoishost --autostart

review collected domain information and eventually add additional second-level domains and sub-domains in scope
$ docker exec -it kaliintelsuite bash
kis_shell> ws=
kis_shell> kisreport domain -w $ws --csv --scope outside | csvcut -c "Second-Level Domain (SLD)","Scope (SLD)","Companies (SLD)" | \
csvsort -c "Second-Level Domain (SLD)" | csvlook
[...]
kis_shell> exit
$ domains=
$ docker exec -it kaliintelsuite kismanage domain -w $ws -s {all,strict} $domains
$ hostnames=
$ docker exec -it kaliintelsuite kismanage hostname -w $ws --add $domains $hostnames

search whois entries of out-of-scope domains for company information (e.g., email address, name servers, phone numbers)
that indicate that domain belong to the target company. if they do, then add them in scope
$ docker exec -it kaliintelsuite bash
kis_shell> ws=
kis_shell> kisreport domain -w $ws --igrep "(($name)|($phone)|($nameserver))" -I whoisdomain --scope outside | csvlook
[...]

review collected network information and eventually add networks in scope
kis_shell> kisreport network -w $ws --csv | csvlook
[...]
kis_shell> exit
$ networks=
$ docker exec -it kaliintelsuite kismanage network -w $ws -s {all,strict} $networks

search whois entries of out-of-scope networks for company information (e.g., email address, name servers, phone numbers)
that indicate that networks belong to the target company. if they do, then add them in scope
$ docker exec -it kaliintelsuite bash
kis_shell> name=
kis_shell> phone=
kis_shell> nameserver=
kis_shell> kisreport network -w $ws --igrep "(($name)|($phone)|($nameserver))" -I whoisnetwork --scope outside | csvlook
[...]

review collected company information and eventually add companies in scope
kis_shell> kisreport company -w $ws --csv | csvlook
[...]
kis_shell> exit
$ companies=
$ docker exec -it kaliintelsuite kismanage company -w $ws -s within $companies

continue collection with updated scope
$ docker exec -it kaliintelsuite kiscollect -w $ws --debug --awsslurp --builtwith --censysdomain \
--certspotter --crtshcompany --crtshdomain --dnsamasspassive --dnscrobatdomain --dnscrobatreversehost \
--dnscrobatreversenetwork --dnscrobattld --dnsdumpster --dnshostpublic --dnsreverselookup --dnsspf --dnssublist3r \
--haveibeenbreach --haveibeenpaste --hostio --hunter --reversewhois --securitytrails --shodanhost --shodannetwork \
--theharvester --virustotal --whoisdomain --whoishost --autostart

run the following command to obtain a list of all in-scope company names. review the items in column "Owns" and
"Owns Scope". if column "Owns Scope" is not "all", then you might want to add the respective item in "Owns" in scope
as well as it belongs to the in-scope company
$ docker exec -it kaliintelsuite bash
kis_shell> ws=
kis_shell> kisreport company -w $ws --csv --scope within | csvlook
[...]

obtain CSV list of identified host names
kis_shell> kisreport domain -w $ws --csv | csvlook
[...]

obtain CSV list of identified IPv4/IPv6 addresses
kis_shell> kisreport host -w $ws --csv | csvlook
[...]
kis_shell> exit

You might want to repeat the above steps until there are no new in-scope second-level domains.


- II. active intel gathering during external and internal penetration tests

check services for default credentials using hydra or changeme; check access to file sharing 
services (e.g., NFS and SMB) using smbclient or showmount; check web applications using gobuster, nikto, 
davtest, or burp suite; obtain TLS information using sslscan, sslyze, and nmap. the collection is performed on 
previously executed nmap scans and a list of in-scope IPv4/IPv6 networks/addresses

before you  start: specify a workspace $ws (e.g., ws=pentest), the paths to the nmap XML files 
(e.g., nmap_paths=/kis/scan1/nmap.xml /kis/scan2/nmap.xml or nmap_paths=/kis/scan1/nmap-tcp-all.xml 
/kis/scan1/nmap-udp-top100.xml) as well as a list of in-scope $networks (e.g., networks=192.168.0.0/24, 
networks=192.168.1.0/24 192.168.1.0/24, networks=192.168.0.1, or networks=192.168.0.1 192.168.0.2)

note that you have to copy the nmap scan results into the docker volume, folder scan1 before starting the import
inside the Docker container from directory /kis:
$ mkdir /var/lib/docker/volumes/kaliintelsuite_kis_data/_data/scan1
$ cp *.xml /var/lib/docker/volumes/kaliintelsuite_kis_data/_data/scan1

import nmap scan results as well as in-scope IPv4/IPv6 networks/addresses into database and execute collection
$ docker exec -it kaliintelsuite kismanage workspace --add $ws
$ docker exec -it kaliintelsuite kismanage network -w $ws --add $networks
$ docker exec -it kaliintelsuite kismanage scan -w $ws --nmap $nmap_paths
$ docker exec -it kaliintelsuite kiscollect -w $ws --debug --strict -t5 --anyservicenmap --certnmap \
--certopenssl --dnsaxfrdomain --dnsaxfrservice --dnsnmap --finger --ftpfilelist --ftphydra --ftpnmap --httpchangeme \
--httpdavtest --httpgobuster --httpgobustersmart --httphydra --httpkiterunner --httpmsfrobotstxt --httpnikto \
--httpnmap --httpntlmnmap --httpwhatweb --ikescan --imapnmap --ipmi --ldapnmap --ldapsearch --msrpcenum --mssqlhydra \
--mssqlnmap --mysqlhydra --mysqlnmap --nbtscan --nfsnmap --ntpq --onesixtyone --oraclesidguess --pgsqlhydra \
--pop3nmap --rdpnmap --rpcclient --rpcinfo --rpcnmap --showmount --smbclient --smbcme --smbfilelist --smbmap \
--smbnmap --smtpnmap --snmpcheck --snmphydra --snmpnmap --snmpwalk --sshchangeme --sshnmap --sslscan --sslyze \
--tlsnmap --telnetnmap --tftpnmap --vncnmap --x11nmap --httpburpsuitepro --autostart

review collected domain information and eventually add domains in scope
$ docker exec -it kaliintelsuite bash
kis_shell> ws=
kis_shell> kisreport domain -w $ws --csv --scope outside | csvcut -c "Second-Level Domain (SLD)","Scope (SLD)","Companies (SLD)" | \
csvsort -c "Second-Level Domain (SLD)" | csvlook
[...]
kis_shell> exit
$ domains=
$ docker exec -it kaliintelsuite kismanage domain -w $ws -s {all,strict} $domains

continue collection based on virtual hosts (might be useful in external penetration tests)
$ docker exec -it kaliintelsuite kiscollect -w $ws --debug --strict -t5 --anyservicenmap --certnmap \
--certopenssl --dnsaxfrdomain --dnsaxfrservice --dnsnmap --finger --ftpfilelist --ftphydra --ftpnmap --httpchangeme \
--httpdavtest --httpgobuster --httpgobustersmart --httphydra --httpkiterunner --httpmsfrobotstxt --httpnikto \
--httpnmap --httpntlmnmap --httpwhatweb --ikescan --imapnmap --ipmi --ldapnmap --ldapsearch --msrpcenum --mssqlhydra \
--mssqlnmap --mysqlhydra --mysqlnmap --nbtscan --nfsnmap --ntpq --onesixtyone --oraclesidguess --pgsqlhydra \
--pop3nmap --rdpnmap --rpcclient --rpcinfo --rpcnmap --showmount --smbclient --smbcme --smbfilelist --smbmap \
--smbnmap --smtpnmap --snmpcheck --snmphydra --snmpnmap --snmpwalk --sshchangeme --sshnmap --sslscan --sslyze \
--tlsnmap --telnetnmap --tftpnmap --vncnmap --x11nmap --httpburpsuitepro --vhost domain --tld --autostart

collect screenshots with aquatone
$ docker exec -it kaliintelsuite bash
kis_shell> ws=
kis_shell> kisreport path -w $ws --scope within --type http --csv | csvcut -c "Full Path" | grep -v "Full Path" | aquatone -out /kis/aquatone
[...]
kis_shell> exit

copy the newly created screenshots form the docker volume:
$ mv /var/lib/docker/volumes/kaliintelsuite_kis_data/_data/aquatone .

export collected information into microsoft excel
$ docker exec -it kaliintelsuite kisreport excel /kis/kis-scan-results.xlsx -w $ws

copy the newly created microsoft excel file form the docker volume:
$ mv /var/lib/docker/volumes/kaliintelsuite_kis_data/_data/kis-scan-results.xlsx .

review scan results of all relevant commands (note that option --visibility hides commands whose output was fully 
processed by KIS and therefore do not require manual inspection anymore)
$ docker exec -it kaliintelsuite bash
kis_shell> ws=
kis_shell> kisreport host -w $ws --text --visibility relevant | less -R
[...]

review scan results of hosts with IPv4/IPv6 addresses $ip1 and $ip2
kis_shell> kisreport host -w $ws --text --filter +$ip1 +$ip2 | less -R
[...]

review scan results of all hosts except hosts with IPv4/IPv6 addresses $ip1 and $ip2
kis_shell> kisreport host -w $ws --text --filter $ip1 $ip2 | less -R
[...]

review scan results of collectors httpnikto and httpgobuster
kis_shell> kisreport host -w $ws --text -I httpnikto httpgobuster | less -R
[...]

review scan results of all collectors except httpnikto and httpgobuster
kis_shell> kisreport host -w $ws --text -X httpnikto httpgobuster | less -R
[...]
kis_shell> exit


III. additional active intel gathering during external penetration test

In addition, to the tests in example I and II, the following commands can be executed on in-scope domains:

# Add domains in scope and execute collection. Note that you might want to specify a DNS server to test for DNS
# zone transfers
$ dns_server=
$ docker exec -it kaliintelsuite kiscollect -w $ws --debug --strict -t5 --dnsamassactive --dnsaxfr \
--dnsdkim --dnsdmarc --dnsenum --dnsgobuster --dnshostpublic --dnsrecon --dnstakeover --httpsqlmap --smtpuserenum \
--vhostgobuster --dnshostpublic --dns-server $dns_server --autostart

# Find additional domains using dnsgen and massdns
$ docker exec -it kaliintelsuite bash
kis_shell> ws=
kis_shell> kisreport domain -w $ws --csv --scope within | csvcut -c "Host Name (HN)" | sort -u | dnsgen - | \
massdns -r /opt/lazydns/resolvers.txt -c 5 -t A -o S --flush 2> /dev/null
[...]
kis_shell> exit

# At the end, do final DNS lookup to ensure that all collected host names are resolved. This ensures that the data is 
# complete for the final report
$ docker exec -it kaliintelsuite kiscollect -w $ws --debug --strict -t5 --dnshostpublic --autostart

Finally, you might want to re-run the entire process to collect further information.
'''
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=SortingHelpFormatter, epilog=epilog)
        collector_group = parser.add_argument_group('collectors', 'use the following arguments to collect intelligence')
        ogroup = parser.add_argument_group('general options', 'use the following arguments to specify how intelligence '
                                                              'is collected')
        testing_group = parser.add_argument_group('internal options', 'this options are only used by KIS itself and '
                                                                      'therefore should not be used by end users')
        producer.add_argparser_arguments(collector_group)
        testing_group.add_argument('--testing',
                                   action="store_true",
                                   help="if specified, then KIS uses the testing instead of the production database")
        ogroup.add_argument("--http-proxy",
                            type=str,
                            help="specify an HTTP(S) proxy that shall be used by collectors in the format "
                                 "https://$ip:$port")
        ogroup.add_argument("-S", "--print-commands",
                            action="store_true",
                            help="print commands to be executed in console instead of executing them. use this option "
                                 "to see how tools (e.g., dnsenum) are executed")
        ogroup.add_argument("--vhost", choices=[item.name for item in VhostChoice],
                            help="per default all HTTP(S) collectors (e.g., httpnikto, httpgobuster) use the IPv4/IPv6 "
                                 "address to scan the target web application. virtual hosts, which are not accessible "
                                 "via this IPv4/IPv6 address are not scanned. if this argument is specified, then the "
                                 "HTTP(S) service intelligence gathering is performed on all known in-scope host "
                                 "names. use choice 'domain' if you want to collect intel just on the host names or "
                                 "use choice 'all' to collect intel based on both - IPv4/IPv6 addresses and host names")
        ogroup.add_argument("--tld",
                            action="store_true",
                            help="usually vhost collectors like httpgobuster do not create commands for "
                                 "top-level domains (TLDs), if they resolve to an in-scope IP address. use this "
                                 "argument to use TLDs as well")
        ogroup.add_argument("--debug",
                            action="store_true",
                            help="prints extra information to log file")
        ogroup.add_argument("-a", "--autostart",
                            action="store_true",
                            help="automatically start collection when application starts")
        ogroup.add_argument("--strict",
                            action="store_true",
                            help="collect information only from services that are definitely open (nmap state is "
                                 "open). ports with nmap status 'open|filtered' are ignored. this option decreases the "
                                 "intel collection time but might not be as comprehensive")
        ogroup.add_argument("--restart", choices=[CommandStatus.failed.name,
                                                  CommandStatus.terminated.name,
                                                  CommandStatus.completed.name], nargs='+',
                            help="per default, kiscollect continues the collection from the last interruption point, "
                                 "and ignores all previously failed or terminated commands. With this option the "
                                 "collection of commands with statuses failed, terminated, or completed can be "
                                 "restarted.")
        ogroup.add_argument("-A", "--analyze",
                            action="store_true",
                            help="re-analyze the already collected information. use this option if you updated the "
                                 "verify_results method of a collector and you want to import the update into the "
                                 "database")
        ogroup.add_argument("--filter",
                            type=str,
                            metavar="IP|NETWORK|HOST",
                            nargs='+',
                            help='list of IPv4/IPv6 networks/addresses or domain/host names that shall be processed.'
                                 'per default, mentioned items are excluded. add + in front of item (e.g., +127.0.0.1) '
                                 ' to process only these items')
        ogroup.add_argument("-t", "--threads",
                            type=int,
                            default=1,
                            help="number of threads that execute collection")
        ogroup.add_argument("-w", "--workspace",
                            type=str,
                            required=True,
                            default=1,
                            help="the workspace within the collection is executed")
        ogroup.add_argument("-l", "--list", action='store_true', help="list existing workspaces")
        ogroup.add_argument("-o", dest="output_dir",
                            type=str,
                            help="KIS uses a temporary working directory to store all temporary files. this working "
                                 "directory is deleted when KIS quits. use this argument to specify an alternative "
                                 "working directory, which must be manually deleted. this argument is usually useful "
                                 "during debugging")
        ogroup.add_argument('--cookies', metavar='N', type=str, nargs='+',
                            help='list of cookies that shall be used by collectors (e.g. "Cookie: JSESSION=123")')
        ogroup.add_argument('--user-agent', metavar='AGENT', type=str,
                            help='set a user agent string')
        ogroup.add_argument('-C', '--combo-file', type=str,
                            help='user name password combo files that shall be used by collectors. the internal '
                                 'structure of the combo file varies depending on the used collectors. for example, '
                                 'hydra collectors have a different structure than medusa collectors')
        ogroup.add_argument("-P","--password-file",
                            type=str,
                            help="file containing passwords that shall be used by collectors")
        ogroup.add_argument("-U", "--user-file",
                            type=str,
                            help="file containing user names that shall be used by collectors")
        ogroup.add_argument("-u", "--user",
                            type=str,
                            help="username that shall be used by collectors")
        ogroup.add_argument("-d", "--domain",
                            type=str,
                            help="domain or workgroup that shall be used by collectors")
        ogroup.add_argument("-p", "--password",
                            type=str,
                            help="password that shall be used by collectors")
        ogroup.add_argument("--hashes",
                            action="store_true",
                            help="if specified, then the passwords specified via arguments -p or -P are interpreted as "
                                 "hashes (this adds arguments -m 'LocalHash' to hydra and -m PASS:HASH to medusa)")
        ogroup.add_argument("-L", "--wordlist-files",
                            type=str, nargs='+',
                            help="list of files containing words (e.g., host names or URLs) that shall be used by "
                                 "collectors. usually KIS creates one command per specified word list")
        ogroup.add_argument("-D", "--delay-min", metavar='MIN', dest="force-delay-min",
                            type=int,
                            help="minimum number of seconds between each operating system command executions. if "
                                 "specified together with option -M, then KIS randomly computes a delay between MIN "
                                 "and MAX per execution else, the delay is always MIN")
        ogroup.add_argument("-M", "--delay-max", metavar='MAX', dest="force-delay-max",
                            type=int,
                            help="maximum number of seconds between each operating system command executions. if "
                                 "specified together with option -D, then KIS randomly computes a delay between MIN "
                                 "and MAX per execution else, the delay is always MAX")
        ogroup.add_argument("-T", "--timeout",
                            dest="force-timeout",
                            type=int,
                            help="the maximum execution time for each collector command. use this argument to ensure "
                                 "that each command is not executed longer than timeout seconds")
        ogroup.add_argument("--dns-server", metavar='SERVER',
                            type=str,
                            help="DNS server (e.g., 8.8.8.8) that shall be used by collectors to query DNS "
                                 "information. otherwise, the system's DNS server is used")
        ogroup.add_argument("--proxychains",
                            action="store_true",
                            help="perform all collections via proxychains")
        ogroup.add_argument("--continue",
                            action="store_true",
                            help="indefinitely repeat the execution of selected collectors")
        args = parser.parse_args()
        if os.geteuid() != 0 and not args.print_commands:
            config = Collector()
            print("{} must be executed with root privileges. afterwards, it is possible to execute "
                  "individual commands with lower privileged users like 'nobody'".format(sys.argv[0]), file=sys.stderr)
            sys.exit(1)
        if args.list:
            engine.print_workspaces()
            sys.exit(1)
        with tempfile.TemporaryDirectory() as temp_dir:
            if args.testing:
                engine.production = False
            arguments = vars(args)
            if args.output_dir and not os.path.isdir(args.output_dir):
                print("output directory '{}' does not exist!".format(args.output_dir), file=sys.stderr)
                sys.exit(1)
            arguments["output_dir"] = args.output_dir if args.output_dir else temp_dir
            producer.init(arguments)
            with engine.session_scope() as session:
                if not engine.get_workspace(session, args.workspace):
                    sys.exit(1)
            if args.user and args.user_file:
                raise ValueError("option --user-file and --user cannot be used together.")
            if args.password and args.password_file:
                raise ValueError("option --password-file and --password cannot be used together.")
            if args.wordlist_files:
                for file in args.wordlist_files:
                    if not os.path.exists(file):
                        raise FileNotFoundError("wordlist '{}' not found.".format(file))
            if args.user_file and not os.path.exists(args.user_file):
                raise FileNotFoundError("user file '{}' not found.".format(args.user_file))
            if args.password_file and not os.path.exists(args.password_file):
                raise FileNotFoundError("password file '{}' not found.".format(args.password_file))
            if args.combo_file and not os.path.exists(args.combo_file):
                raise FileNotFoundError("combo file '{}' not found.".format(args.combo_file))
            log_level = logging.INFO
            if args.analyze:
                log_level = logging.WARNING
            if args.debug:
                log_level = logging.DEBUG
            if not args.print_commands:
                logging.basicConfig(filename=BaseConfig.get_log_file(),
                                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                                    datefmt='%Y-%m-%d %H:%M:%S',
                                    level=log_level)
                logger = logging.getLogger(sys.argv[0])
                logger.info("$ {}".format(" ".join(sys.argv)))

            # Let's get started
            if args.print_commands:
                producer.start()
                producer.join()
            else:
                KisCollectConsole(args=args, producer_thread=producer).cmdloop()
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
