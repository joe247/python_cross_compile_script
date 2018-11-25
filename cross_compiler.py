#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ####################################################
# Copyright (C) 2018 DeadSix27 (https://github.com/DeadSix27/python_cross_compile_script)
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ###################################################

# ###################################################
# ### Settings are located in cross_compiler.yaml ###
# ###### That file will be generated on start. ######
# ###################################################

# ###################################################
# ################ REQUIRED PACKAGES ################
# ###################################################
# Package dependencies (some may be missing):
# sudo apt install build-essential autogen libtool libtool-bin pkg-config texinfo yasm git make automake gcc pax cvs subversion flex bison patch mercurial cmake gettext autopoint libxslt1.1 docbook-utils rake docbook-xsl gperf gyp p7zip-full p7zip docbook-to-man pandoc rst2pdf

import progressbar # Run pip3 install progressbar2
import requests # Run pip3 install requests
import yaml

import os.path,logging,re,subprocess,sys,shutil,urllib.request,urllib.parse,stat
import hashlib,glob,traceback,time,zlib,codecs,argparse
import http.cookiejar
from multiprocessing import cpu_count
from pathlib import Path
from urllib.parse import urlparse
from collections import OrderedDict

class Colors: #ansi colors
	RESET           = '\033[0m'
	BLACK           = '\033[30m'
	RED             = '\033[31m'
	GREEN           = '\033[32m'
	YELLOW          = '\033[33m'
	BLUE            = '\033[34m'
	MAGENTA         = '\033[35m'
	CYAN            = '\033[36m'
	WHITE           = '\033[37m'
	LIGHTBLACK_EX   = '\033[90m' # those seem to work on the major OS so meh.
	LIGHTRED_EX     = '\033[91m'
	LIGHTGREEN_EX   = '\033[92m'
	LIGHTYELLOW_EX  = '\033[93m'
	LIGHTBLUE_EX    = '\033[94m'
	LIGHTMAGENTA_EX = '\033[95m'
	LIGHTCYAN_EX    = '\033[96m'
	LIGHTWHITE_EX   = '\033[9m'

class MissingDependency(Exception):
	__module__ = 'exceptions'
	def __init__(self, message):
		self.message = message

class MyLogFormatter(logging.Formatter):
	def __init__(self,l,ld):
		MyLogFormatter.log_format = l
		MyLogFormatter.log_date_format = ld
		MyLogFormatter.inf_fmt  = Colors.LIGHTCYAN_EX   + MyLogFormatter.log_format + Colors.RESET
		MyLogFormatter.err_fmt  = Colors.LIGHTRED_EX    + MyLogFormatter.log_format + Colors.RESET
		MyLogFormatter.dbg_fmt  = Colors.LIGHTYELLOW_EX + MyLogFormatter.log_format + Colors.RESET
		MyLogFormatter.war_fmt  = Colors.YELLOW         + MyLogFormatter.log_format + Colors.RESET
		super().__init__(fmt="%(levelno)d: %(msg)s", datefmt=MyLogFormatter.log_date_format, style='%')

	def format(self, record):
		if not hasattr(record,"type"):
			record.type = ""
		else:
			record.type = "[" + record.type.upper() + "]"
		
		format_orig = self._style._fmt
		if record.levelno == logging.DEBUG:
			self._style._fmt = MyLogFormatter.dbg_fmt
		elif record.levelno == logging.INFO:
			self._style._fmt = MyLogFormatter.inf_fmt
		elif record.levelno == logging.ERROR:
			self._style._fmt = MyLogFormatter.err_fmt
		elif record.levelno == logging.WARNING:
			self._style._fmt = MyLogFormatter.war_fmt
		result = logging.Formatter.format(self, record)
		self._style._fmt = format_orig
		return result

class CrossCompileScript:

	def __init__(self,products,depends,variables):
		sys.dont_write_bytecode     = True # Avoid __pycache__ folder, never liked that solution.
		self.PRODUCTS               = products
		self.DEPENDS                = depends
		self.VARIABLES              = variables
		hdlr                        = logging.StreamHandler(sys.stdout)
		fmt                         = MyLogFormatter("[%(asctime)s][%(levelname)s]%(type)s %(message)s","%H:%M:%S")
		hdlr.setFormatter(fmt)
		self.logger                 = logging.getLogger(__name__)
		self.logger.addHandler(hdlr)
		self.logger.setLevel(logging.INFO)
		self.config                 = self.loadConfig()
		fmt                         = MyLogFormatter(self.config["script"]["log_format"],self.config["script"]["log_date_format"])
		hdlr.setFormatter(fmt)
		self.init()

	def loadConfig(self):
		config_file = os.path.splitext(os.path.basename(__file__))[0] + ".yaml"
		
		if not os.path.isfile(config_file):
			self.writeDefaultConfig(config_file)
			
		with open(config_file, 'r') as cs:
			try:
				return yaml.load(cs)
			except yaml.YAMLError as e:
				self.logger.error("Failed to load config file " + str(e))
				traceback.print_exc()
				sys.exit(1)
				
	def writeDefaultConfig(self,config_file):
		self.config = {
			'version': 1.0,
			'script': {
				'debug' : False,
				'quiet': False,
				'log_date_format': '%H:%M:%S',
				'log_format': '[%(asctime)s][%(levelname)s]%(type)s %(message)s',
				'product_order': ['mpv', 'ffmpeg_static', 'ffmpeg_shared'],
				'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:63.0) Gecko/20100101 Firefox/63.0',
				'mingw_script_url' : 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/toolchain_build_scripts/build_mingw_toolchain.py',
				'overwrite_mingw_script': True,
			},
			'toolchain': {
				'bitness': [64,],
				'cpu_count': cpu_count(),
				'mingw_commit': None,
				'mingw_debug_build': False,
				'mingw_dir': 'toolchain',
				'work_dir': 'workdir',
				'original_cflags': '-O3',
			}
		}
		with open(config_file,"w",encoding="utf-8") as f:
			f.write(yaml.dump(self.config))
		self.logger.info("Wrote default configuration file to: '%s'" % (config_file))

	def init(self):
		self.product_order          = self.config["script"]["product_order"]
		self.fullCurrentPath        = os.getcwd()
		self.fullWorkDir            = os.path.join(self.fullCurrentPath,self.config["toolchain"]["work_dir"])
		self.mingwDir               = self.config["toolchain"]["mingw_dir"]
		self.fullProductDir         = None
		self.targetBitness          = self.config["toolchain"]["bitness"]
		self.originalPATH           = os.environ["PATH"]
		self.mingwScriptURL         = self.config["script"]["mingw_script_url"]
		self.targetHost             = None
		self.targetPrefix           = None
		self.mingwBinpath           = None
		self.mingwBinpath2          = None
		self.fullCrossPrefix        = None
		self.makePrefixOptions      = None
		self.bitnessDir             = None
		self.bitnessDir2            = None
		self.winBitnessDir          = None
		self.pkgConfigPath          = None
		self.bareCrossPrefix        = None
		self.cpuCount               = None
		self.originalCflags         = None
		self.buildLogFile           = None
		self.quietMode              = self.config["script"]["quiet"]
		self.debugMode              = self.config["script"]["debug"]
		self.userAgent              = self.config["script"]["user_agent"]
		if self.debugMode:
			self.init_debugMode()
		if self.quietMode:
			self.init_quietMode()

	def init_quietMode(self):
		self.logger.warning('Quiet mode is enabled')
		self.buildLogFile = codecs.open("raw_build.log","w","utf-8")
	def init_debugMode(self):
		self.logger.setLevel(logging.DEBUG)
		self.logger.debug('Debugging is on')

	def listify_pdeps(self,pdlist,type):
		class customArgsAction(argparse.Action):
			def __call__(self, parser, args, values, option_string=None):
				format = "CLI"
				if args.markdown:
					format = "MD"
				if args.csv:
					format = "CSV"

				if format == "CLI":
					longestName = 0
					longestVer = 1
					for key,val in pdlist.items():
						if '_info' in val:
							if 'version' in val['_info']:
								if len(val['_info']['version']) > longestVer:
									longestVer = len(val['_info']['version'])
							name = key
							if len(name) > longestName:
								longestName = len(name)
							# if 'fancy_name' in val['_info']:
								# if len(val['_info']['fancy_name']) > longestName:
									# longestName = len(val['_info']['fancy_name'])
						else:
							if len(key) > longestName:
								longestName = len(key)

					HEADER = "Product"
					if type == "D":
						HEADER = "Dependency"
					if longestName < len('Dependency'):
						longestName = len('Dependency')
					HEADER_V = "Version"
					if longestVer < len(HEADER_V):
						longestVer = len(HEADER_V)

					print(' {0} - {1}'.format(HEADER.rjust(longestName,' '),HEADER_V.ljust(longestVer, ' ')))
					print('')

					for key,val in sorted(pdlist.items()):
						ver = Colors.RED + "(no version)" + Colors.RESET
						if '_info' in val:
							if 'version' in val['_info']:
								ver = Colors.GREEN + val['_info']['version'] + Colors.RESET
						name = key
						# if '_info' in val:
							# if 'fancy_name' in val['_info']:
								# name = val['_info']['fancy_name']

						print(' {0} - {1}'.format(name.rjust(longestName,' '),ver.ljust(longestVer, ' ')))
				elif format == "MD":
					longestName = 0
					longestVer = 1
					for key,val in pdlist.items():
						if '_info' in val:
							if 'version' in val['_info']:
								if len(val['_info']['version']) > longestVer:
									longestVer = len(val['_info']['version'])
							if 'fancy_name' in val['_info']:
								if len(val['_info']['fancy_name']) > longestName:
									longestName = len(val['_info']['fancy_name'])
						else:
							if len(key) > longestName:
								longestName = len(key)

					HEADER = "Product"
					if type == "D":
						HEADER = "Dependency"
					if longestName < len('Dependency'):
						longestName = len('Dependency')
					HEADER_V = "Version"
					if longestVer < len(HEADER_V):
						longestVer = len(HEADER_V)

					print('| {0} | {1} |'.format(HEADER.ljust(longestName,' '),HEADER_V.ljust(longestVer,' ')))
					print('| {0}:|:{1} |'.format(longestName * '-', longestVer * '-'))
					for key,val in sorted(pdlist.items()):
						if '_info' in val:
							ver = "?"
							name = key
							if 'version' in val['_info']:
								ver = val['_info']['version']
							if 'fancy_name' in val['_info']:
								name = val['_info']['fancy_name']
							print('| {0} | {1} |'.format(name.ljust(longestName,' '),ver.ljust(longestVer,' ')))
				else:
					print(";".join( sorted(pdlist.keys()) ))
				setattr(args, self.dest, values)
				parser.exit()
		return customArgsAction

	def assembleConfigHelps(self,pdlist,type,main):
		class customArgsAction(argparse.Action):
			def __call__(self, parser, args, values, option_string=None):
				main.quietMode = True
				main.init_quietMode()
				main.prepareBuilding(64)
				main.build_mingw(64)
				main.initBuildFolders()
				for k,v in pdlist.items():
					if '_disabled' not in v:
						if '_info' in v:
							beforePath = os.getcwd()
							path = main.get_thing_path(k,v,type)
							main.cchdir(path)
							if os.path.isfile(os.path.join(path,"configure")):
								os.system("./configure --help")
							if os.path.isfile(os.path.join(path,"waf")):
								os.system("./waf --help")
							main.cchdir(beforePath)
							print("-------------------")
				setattr(args, self.dest, values)
				parser.exit()
		return customArgsAction

	def commandLineEntrace(self):
		class epiFormatter(argparse.RawDescriptionHelpFormatter):
			w = shutil.get_terminal_size((120, 10))[0]
			def __init__(self, max_help_position=w, width=w, *args, **kwargs):
				kwargs['max_help_position'] = max_help_position
				kwargs['width'] = width
				super(epiFormatter, self).__init__(*args, **kwargs)
			def _split_lines(self, text, width):
				return text.splitlines()

		_epilog = 'Copyright (C) 2018 DeadSix27 (https://github.com/DeadSix27/python_cross_compile_script)\n\n This Source Code Form is subject to the terms of the Mozilla Public\n License, v. 2.0. If a copy of the MPL was not distributed with this\n file, You can obtain one at https://mozilla.org/MPL/2.0/.\n '

		parser = argparse.ArgumentParser(formatter_class=epiFormatter, epilog=_epilog)
		parser.description = Colors.CYAN + 'Pythonic Cross Compile Helper (MPL2.0)' + Colors.RESET + '\n\nExample usages:' \
			'\n "{0} list -p"             - lists all the products' \
			'\n "{0} -a"                  - builds everything' \
			'\n "{0} -f -d libx264"       - forces the rebuilding of libx264' \
			'\n "{0} -pl x265_10bit,mpv"  - builds this list of products in that order' \
			'\n "{0} -q -p ffmpeg_static" - will quietly build ffmpeg-static'.format(parser.prog)

		subparsers = parser.add_subparsers(help='Sub commands')

		list_p = subparsers.add_parser('list', help= 'Type: \'' + parser.prog + ' list --help\' for more help')

		list_p.add_argument('-md', '--markdown', help='Print list in markdown format', action='store_true')
		list_p.add_argument('-cv', '--csv', help='Print list as CSV-like string', action='store_true')
		list_p_group1 = list_p.add_mutually_exclusive_group(required=True)
		list_p_group1.add_argument('-p', '--products',    nargs=0, help='List all products',     action=self.listify_pdeps(self.PRODUCTS,"P"))
		list_p_group1.add_argument('-d', '--dependencies', nargs=0, help='List all dependencies', action=self.listify_pdeps(self.DEPENDS, "D"))


		chelps_p = subparsers.add_parser('chelps', help= 'Type: \'' + parser.prog + ' chelps --help\' for more help')
		chelps_p_group1 = chelps_p.add_mutually_exclusive_group(required=True)
		chelps_p_group1.add_argument('-p', '--products',    nargs=0, help='Write all product config helps to confighelps.txt',     action=self.assembleConfigHelps(self.PRODUCTS,"P",self))
		chelps_p_group1.add_argument('-d', '--dependencies', nargs=0, help='Write all dependency config helps to confighelps.txt',  action=self.assembleConfigHelps(self.DEPENDS, "D",self))


		group2 = parser.add_mutually_exclusive_group( required = True )
		group2.add_argument( '-p',  '--build-product',         dest='PRODUCT',         help='Build this product (and dependencies)'                        )
		group2.add_argument( '-pl', '--build-product_list',    dest='PRODUCT_LIST',    help='Build this product list'                                      )
		group2.add_argument( '-d',  '--build-dependency',      dest='DEPENDENCY',      help='Build this dependency'                                        )
		group2.add_argument( '-dl', '--build-dependency_list', dest='DEPENDENCY_LIST', help='Build this dependency list'                                   )
		group2.add_argument( '-a',  '--build-all',                                     help='Build all products (according to order)', action='store_true' )
		parser.add_argument( '-q',  '--quiet',                                         help='Only show info lines'                   , action='store_true' )
		parser.add_argument( '-f',  '--force',                                         help='Force rebuild, deletes already files'   , action='store_true' )
		parser.add_argument( '-g',  '--debug',                                         help='Show debug information'                 , action='store_true' )
		parser.add_argument( '-s',  '--skip-depends',                                  help='Skip dependencies when building'        , action='store_true' )

		if len(sys.argv)==1:
			self.defaultEntrace()
		else:
			def errorOut(p,t,m=None):
				if m == None:
					fullStr = Colors.LIGHTRED_EX + 'Error:\n ' + Colors.CYAN + '\'{0}\'' + Colors.LIGHTRED_EX + ' is not a valid {2}\n Type: ' + Colors.CYAN + '\'{1} list --products/--dependencies\'' + Colors.LIGHTRED_EX + ' for a full list'
					print( fullStr.format ( p, os.path.basename(__file__), "Product" if t == "PRODUCT" else "Dependency" ) + Colors.RESET )
				else:
					print(m)
				exit(1)
			args = parser.parse_args()
			forceRebuild = False
			if args.debug:
				self.debugMode = True
				self.init_debugMode()
			if args.quiet:
				self.quietMode = True
				self.init_quietMode()
			if args.force:
				forceRebuild = True
			thingToBuild = None
			buildType = None

			finalThingList = []

			if args.PRODUCT:
				buildType = "PRODUCT"
				thingToBuild = args.PRODUCT
				if thingToBuild in self.PRODUCTS:
					finalThingList.append(thingToBuild)
				else:
					errorOut(thingToBuild,buildType)

			elif args.DEPENDENCY:
				buildType = "DEPENDENCY"
				thingToBuild = args.DEPENDENCY
				if thingToBuild in self.DEPENDS:
					finalThingList.append(thingToBuild)
				else:
					errorOut(thingToBuild,buildType)

			elif args.DEPENDENCY_LIST:
				buildType = "DEPENDENCY"
				thingToBuild = args.DEPENDENCY_LIST
				if "," not in thingToBuild:
					errorOut(None,None,"Error: are you sure the list format is correct? It must be dependency1,dependency2,dependency3, ...")
				for d in thingToBuild.split(","):
					if d in self.DEPENDS:
						finalThingList.append(d)
					else:
						errorOut(d,buildType)

			elif args.PRODUCT_LIST:
				buildType = "PRODUCT"
				thingToBuild = args.PRODUCT_LIST
				if "," not in thingToBuild:
					errorOut(None,None,"Error: are you sure the list format is correct? It must be product1,product2,product3, ...")
				for d in thingToBuild.split(","):
					if d in self.PRODUCTS:
						finalThingList.append(d)
					else:
						errorOut(d,buildType)

			elif args.build_all:
				self.defaultEntrace()
				return

			self.logger.warning('Starting custom build process for: {0}'.format(thingToBuild))
			
			skipDeps = False
			
			if args.skip_depends:
				skipDeps = True

			for thing in finalThingList:
				for b in self.targetBitness:
					main.prepareBuilding(b)
					main.build_mingw(b)
					main.initBuildFolders()
					if buildType == "PRODUCT":
						self.build_thing(thing,self.PRODUCTS[thing],buildType,forceRebuild,skipDeps)
					else:
						self.build_thing(thing,self.DEPENDS[thing],buildType,forceRebuild,skipDeps)
					main.finishBuilding()

	def defaultEntrace(self):
		for b in self.targetBitness:
			self.prepareBuilding(b)
			self.build_mingw(b)
			self.initBuildFolders()
			for p in self.product_order:
				self.build_thing(p,self.PRODUCTS[p],"PRODUCT")
			self.finishBuilding()

	def finishBuilding(self):
		self.cchdir("..")

	def prepareBuilding(self,b):
		self.logger.info('Starting build script')
		if not os.path.isdir(self.fullWorkDir):
			self.logger.info("Creating workdir: %s" % (self.fullWorkDir))
			os.makedirs(self.fullWorkDir, exist_ok=True)
		self.cchdir(self.fullWorkDir)

		self.bitnessDir         = "x86_64" if b is 64 else "i686" # e.g x86_64
		self.bitnessDir2        = "x86_64" if b is 64 else "x86" # just for vpx...
		self.bitnessDir3        = "mingw64" if b is 64 else "mingw" # just for openssl...
		self.winBitnessDir      = "win64" if b is 64 else "win32" # e.g win64
		self.targetHost         = "{0}-w64-mingw32".format ( self.bitnessDir ) # e.g x86_64-w64-mingw32
		self.targetPrefix       = "{0}/{1}/{2}-w64-mingw32/{3}".format( self.fullWorkDir, self.mingwDir, self.bitnessDir, self.targetHost ) # workdir/xcompilers/mingw-w64-x86_64/x86_64-w64-mingw32
		self.inTreePrefix       = "{0}".format( os.path.join(self.fullWorkDir,self.bitnessDir) ) # workdir/x86_64
		self.offtreePrefix      = "{0}".format( os.path.join(self.fullWorkDir,self.bitnessDir + "_offtree") ) # workdir/x86_64_offtree
		self.targetSubPrefix    = "{0}/{1}/{2}-w64-mingw32".format( self.fullWorkDir, self.mingwDir, self.bitnessDir ) # e.g workdir/xcompilers/mingw-w64-x86_64
		self.mingwBinpath       = "{0}/{1}/{2}-w64-mingw32/bin".format( self.fullWorkDir, self.mingwDir, self.bitnessDir ) # e.g workdir/xcompilers/mingw-w64-x86_64/bin
		self.mingwBinpath2      = "{0}/{1}/{2}-w64-mingw32/{2}-w64-mingw32/bin".format( self.fullWorkDir, self.mingwDir, self.bitnessDir ) # e.g workdir/xcompilers/x86_64-w64-mingw32/x86_64-w64-mingw32/bin
		self.fullCrossPrefix    = "{0}/{1}-w64-mingw32-".format( self.mingwBinpath, self.bitnessDir ) # e.g workdir/xcompilers/mingw-w64-x86_64/bin/x86_64-w64-mingw32-
		self.bareCrossPrefix    = "{0}-w64-mingw32-".format( self.bitnessDir ) # e.g x86_64-w64-mingw32-
		self.makePrefixOptions  = "CC={cross_prefix_bare}gcc AR={cross_prefix_bare}ar PREFIX={target_prefix} RANLIB={cross_prefix_bare}ranlib LD={cross_prefix_bare}ld STRIP={cross_prefix_bare}strip CXX={cross_prefix_bare}g++".format( cross_prefix_bare=self.bareCrossPrefix, target_prefix=self.targetPrefix )
		self.cmakePrefixOptions = "-G\"Unix Makefiles\" -DCMAKE_SYSTEM_PROCESSOR=\"{bitness}\" -DENABLE_STATIC_RUNTIME=1 -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_RANLIB={cross_prefix_full}ranlib -DCMAKE_C_COMPILER={cross_prefix_full}gcc -DCMAKE_CXX_COMPILER={cross_prefix_full}g++ -DCMAKE_RC_COMPILER={cross_prefix_full}windres -DCMAKE_FIND_ROOT_PATH={target_prefix}".format(cross_prefix_full=self.fullCrossPrefix, target_prefix=self.targetPrefix,bitness=self.bitnessDir )
		self.pkgConfigPath      = "{0}/lib/pkgconfig".format( self.targetPrefix ) #e.g workdir/xcompilers/mingw-w64-x86_64/x86_64-w64-mingw32/lib/pkgconfig
		self.fullProductDir     = os.path.join(self.fullWorkDir,self.bitnessDir + "_products")
		self.currentBitness     = b
		self.mesonEnvFile       = os.path.join(self.targetSubPrefix, "meson_environment.txt")
		self.cpuCount           = self.config["toolchain"]["cpu_count"]
		self.originalCflags     = self.config["toolchain"]["original_cflags"]

		if self.debugMode:
			print('self.bitnessDir = \n'         + self.bitnessDir + '\n\n')
			print('self.bitnessDir2 = \n'        + self.bitnessDir2 + '\n\n')
			print('self.winBitnessDir = \n'      + self.winBitnessDir + '\n\n')
			print('self.targetHost = \n'      + self.targetHost + '\n\n')
			print('self.targetPrefix = \n'      + self.targetPrefix + '\n\n')
			print('self.mingwBinpath = \n'       + self.mingwBinpath + '\n\n')
			print('self.fullCrossPrefix = \n'    + self.fullCrossPrefix + '\n\n')
			print('self.bareCrossPrefix = \n'    + self.bareCrossPrefix + '\n\n')
			print('self.makePrefixOptions = \n'  + self.makePrefixOptions + '\n\n')
			print('self.cmakePrefixOptions = \n' + self.cmakePrefixOptions + '\n\n')
			print('self.pkgConfigPath = \n'      + self.pkgConfigPath + '\n\n')
			print('self.fullProductDir = \n'     + self.fullProductDir + '\n\n')
			print('self.currentBitness = \n'     + str(self.currentBitness) + '\n\n')
			print('PATH = \n'                    + os.environ["PATH"] + '\n\n')

		os.environ["PATH"]           = "{0}:{1}".format ( self.mingwBinpath, self.originalPATH )
		#os.environ["PATH"]           = "{0}:{1}:{2}".format ( self.mingwBinpath, os.path.join(self.targetPrefix,'bin'), self.originalPATH ) #todo properly test this..
		os.environ["PKG_CONFIG_PATH"] = self.pkgConfigPath
		os.environ["PKG_CONFIG_LIBDIR"] = ""
	#:
	def initBuildFolders(self):
		if not os.path.isdir(self.bitnessDir):
			self.logger.info("Creating bitdir: {0}".format( self.bitnessDir ))
			os.makedirs(self.bitnessDir, exist_ok=True)

		if not os.path.isdir(self.bitnessDir + "_products"):
			self.logger.info("Creating bitdir: {0}".format( self.bitnessDir + "_products" ))
			os.makedirs(self.bitnessDir + "_products", exist_ok=True)

		if not os.path.isdir(self.bitnessDir + "_offtree"):
			self.logger.info("Creating bitdir: {0}".format( self.bitnessDir + "_offtree" ))
			os.makedirs(self.bitnessDir + "_offtree", exist_ok=True)

	def build_mingw(self,bitness):
		gcc_bin = os.path.join(self.mingwBinpath, self.bitnessDir + "-w64-mingw32-gcc")

		if os.path.isfile(gcc_bin):
			gccOutput = subprocess.check_output(gcc_bin + " -v", shell=True, stderr=subprocess.STDOUT).decode("utf-8")
			workingGcc = re.compile("^Target: .*-w64-mingw32$", re.MULTILINE).findall(gccOutput)
			if len(workingGcc) > 0:
				self.logger.info("MinGW-w64 install is working!")
				return
			else:
				raise Exception("GCC is not working properly, target is not mingw32.")
				exit(1)

		elif not os.path.isdir(self.mingwDir):
			self.logger.info("Building MinGW-w64 in folder '{0}'".format( self.mingwDir ))

			# os.makedirs(self.mingwDir, exist_ok=True)

			os.unsetenv("CFLAGS")

			# self.cchdir(self.mingwDir)
			
			download_toolchain_script = False
			if not os.path.isfile(os.path.join(self.fullCurrentPath,"build_mingw_toolchain.py")):
				download_toolchain_script = True
			elif self.config["script"]["overwrite_mingw_script"]:
				download_toolchain_script = True
				
			mingw_script_file = None
			
			if download_toolchain_script:
				mingw_script_file = self.download_file(self.mingwScriptURL,outputPath = self.fullCurrentPath)

			def toolchainBuildStatus(data):
				self.logger.info(data)

			from build_mingw_toolchain import MinGW64ToolChainBuilder

			toolchainBuilder = MinGW64ToolChainBuilder()

			toolchainBuilder.workDir = self.mingwDir
			if self.config["toolchain"]["mingw_commit"] != None:
				toolchainBuilder.setMinGWcheckout(self.config["toolchain"]["mingw_commit"])
			toolchainBuilder.setDebugBuild(self.config["toolchain"]["mingw_debug_build"])
			toolchainBuilder.onStatusUpdate += toolchainBuildStatus
			toolchainBuilder.build()

			# self.cchdir("..")
		else:
			raise Exception("It looks like the previous MinGW build failed, please delete the folder '%s' and re-run this script" % self.mingwDir)
	#:

	def downloadHeader(self,url):
		destination = os.path.join(self.targetPrefix,"include")
		fileName = os.path.basename(urlparse(url).path)

		if not os.path.isfile(os.path.join(destination,fileName)):
			fname = self.download_file(url)
			self.logger.debug("Moving Header File: '{0}' to '{1}'".format( fname, destination ))
			shutil.move(fname, destination)
		else:
			self.logger.debug("Header File: '{0}' already downloaded".format( fileName ))

	def download_file(self,url=None, outputFileName=None, outputPath=None, bytes=False):
		def fmt_size(num, suffix="B"):
				for unit in ["","Ki","Mi","Gi","Ti","Pi","Ei","Zi"]:
					if abs(num) < 1024.0:
						return "%3.1f%s%s" % (num, unit, suffix)
					num /= 1024.0
				return "%.1f%s%s" % (num, "Yi", suffix)
		#:
		if not url:
			raise Exception("No URL specified.")

		if outputPath is None: # Default to current dir.
			outputPath = os.getcwd()
		else:
			if not os.path.isdir(outputPath):
				raise Exception('Specified path "{0}" does not exist'.format(outputPath))

		fileName = os.path.basename(url) # Get URL filename
		userAgent = self.userAgent

		if 'sourceforge.net' in url.lower():
			userAgent = 'wget/1.18' # sourceforce <3 wget

		if url.lower().startswith("ftp://"):
			self.logger.info("Requesting : {0}".format(url))
			if outputFileName != None:
				fileName = outputFileName
			fullOutputPath = os.path.join(outputPath,fileName)
			urllib.request.urlretrieve(url, fullOutputPath)
			return fullOutputPath

		if url.lower().startswith("file://"):
			url = url.replace("file://","")
			self.logger.info("Copying : {0}".format(url))
			if outputFileName != None:
				fileName = outputFileName
			fullOutputPath = os.path.join(outputPath,fileName)
			try:
				shutil.copyfile(url, fullOutputPath)
			except Exception as e:
				print(e)
				exit(1)
			return fullOutputPath

		req = requests.get(url, stream=True, headers = { "User-Agent": userAgent } )

		if req.status_code != 200:
			req.raise_for_status()

		if "content-disposition" in req.headers:
			reSponse = re.findall("filename=(.+)", req.headers["content-disposition"])
			if reSponse == None:
				fileName = os.path.basename(url)
			else:
				fileName = reSponse[0]

		size = None
		compressed = False
		if "Content-Length" in req.headers:
			size = int(req.headers["Content-Length"])

		if "Content-Encoding" in req.headers:
			if req.headers["Content-Encoding"] == "gzip":
				compressed = True

		self.logger.info("Requesting : {0} - {1}".format(url, fmt_size(size) if size!=None else "?" ))

		# terms = shutil.get_terminal_size((100,100))
		# filler = 0
		# if terms[0] > 100:
		# 	filler = int(terms[0]/4)

		widgetsNoSize = [
			progressbar.FormatCustomText("Downloading: {:25.25}".format(os.path.basename(fileName)))," ",
			progressbar.AnimatedMarker(markers='|/-\\'), " ",
			progressbar.DataSize()
			# " "*filler
		]
		widgets = [
			progressbar.FormatCustomText("Downloading: {:25.25}".format(os.path.basename(fileName)))," ",
			progressbar.Percentage(), " ",
			progressbar.Bar(fill=chr(9617), marker=chr(9608), left="[", right="]"), " ",
			progressbar.DataSize(), "/", progressbar.DataSize(variable="max_value"), " |",
			progressbar.AdaptiveTransferSpeed(), " | ",
			progressbar.ETA(),
			# " "*filler
		]
		pbar = None
		if size == None:
			pbar = progressbar.ProgressBar(widgets=widgetsNoSize,maxval=progressbar.UnknownLength)
		else:
			pbar = progressbar.ProgressBar(widgets=widgets,maxval=size)

		if outputFileName != None:
			fileName = outputFileName
		fullOutputPath = os.path.join(outputPath,fileName)

		updateSize = 0

		if isinstance(pbar.max_value, int):
			updateSize = pbar.max_value if pbar.max_value < 1024 else 1024

		if bytes == True:
			output = b""
			bytesrecv = 0
			pbar.start()
			for buffer in req.iter_content(chunk_size=1024):
				if buffer:
					 output += buffer
				if compressed:
					pbar.update(updateSize)
				else:
					pbar.update(bytesrecv)
				bytesrecv += len(buffer)
			pbar.finish()
			return output
		else:
			with open(fullOutputPath, "wb") as file:
				bytesrecv = 0
				pbar.start()
				for buffer in req.iter_content(chunk_size=1024):
					if buffer:
						file.write(buffer)
						file.flush()
					if compressed:
						pbar.update(updateSize)
					else:
						pbar.update(bytesrecv)
					bytesrecv += len(buffer)
				pbar.finish()

				return fullOutputPath
	#:
	
	def create_meson_environment_file(self):
		if not os.path.isfile(self.mesonEnvFile):
			self.logger.info("Creating Meson Environment file at: '%s'" % (self.mesonEnvFile))
			with open(self.mesonEnvFile, 'w') as f:
				f.write("[binaries]\n")
				f.write("c = '{0}gcc'\n".format(self.fullCrossPrefix))
				f.write("cpp = '{0}g++'\n".format(self.fullCrossPrefix))
				f.write("ld = '{0}ld'\n".format(self.fullCrossPrefix))
				f.write("ar = '{0}ar'\n".format(self.fullCrossPrefix))
				f.write("strip = '{0}strip'\n".format(self.fullCrossPrefix))
				f.write("windres = '{0}windres'\n".format(self.fullCrossPrefix))
				f.write("ranlib = '{0}ranlib'\n".format(self.fullCrossPrefix))
				f.write("pkgconfig = '{0}pkg-config'\n".format(self.fullCrossPrefix)) # ??
				f.write("dlltool = '{0}dlltool'\n".format(self.fullCrossPrefix))
				f.write("gendef = '{0}/gendef'\n".format(self.mingwBinpath))
				f.write("needs_exe_wrapper = false\n")
				f.write("#exe_wrapper = 'wine' # A command used to run generated executables.\n")
				f.write("\n")
				f.write("[host_machine]\n")
				f.write("system = 'windows'\n")
				f.write("cpu_family = '{0}'\n".format(self.bitnessDir))
				f.write("cpu = '{0}'\n".format(self.bitnessDir))
				f.write("endian = 'little'\n")
				f.write("\n")
				f.write("[target_machine]\n")
				f.write("system = 'windows'\n")
				f.write("cpu_family = '{0}'\n".format(self.bitnessDir))
				f.write("cpu = '{0}'\n".format(self.bitnessDir))
				f.write("endian = 'little'\n")
				f.write("\n")
				f.write("[properties]\n")
				f.write("c_link_args = ['-static', '-static-libgcc']\n")
				f.write("# sys_root = Directory that contains 'bin', 'lib', etc for the toolchain and system libraries\n")
				f.write("sys_root = '{0}'\n".format(self.targetSubPrefix))
				f.close()

	def download_file_old(self,link, targetName = None):
		_MAX_REDIRECTS = 5
		cj = http.cookiejar.CookieJar()
		class RHandler(urllib.request.HTTPRedirectHandler):
			def http_error_301(self, req, fp, code, msg, headers):
				result = urllib.request.HTTPRedirectHandler.http_error_301(
					self, req, fp, code, msg, headers)
				result.status = code
				return result

			def http_error_302(self, req, fp, code, msg, headers):
				result = urllib.request.HTTPRedirectHandler.http_error_302(
					self, req, fp, code, msg, headers)
				result.status = code
				return result

		def sizeof_fmt(num, suffix='B'): # sizeof_fmt is courtesy of https://stackoverflow.com/a/1094933
			for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
				if abs(num) < 1024.0:
					return "%3.1f%s%s" % (num, unit, suffix)
				num /= 1024.0
			return "%.1f%s%s" % (num, 'Yi', suffix)

		link = urllib.parse.unquote(link)
		_CHUNKSIZE = 10240

		if not link.lower().startswith("https") and not link.lower().startswith("file"):
			self.logger.warning("WARNING: Using non-SSL http is not advised..") # gotta get peoples attention somehow eh?

		fname = None

		if targetName == None:
			fname = os.path.basename(urlparse(link).path)
		else:
			fname = targetName

		#print("Downloading {0} to {1} ".format( link, fname) )

		ua = 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36'
		if 'sourceforge.net' in link.lower():
			ua = 'wget/1.18' # sourceforge gives direct dls to wget agents.

		f = open(fname,'ab')
		hdrs = [ # act like chrome
				('Connection'                , 'keep-alive'),
				('Pragma'                    , 'no-cache'),
				('Cache-Control'             , 'no-cache'),
				('Upgrade-Insecure-Requests' , '1'),
				('User-Agent'                , ua),
				('Accept'                    , 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'),
				# ('Accept-Encoding'           , 'gzip'),
				('Accept-Language'           , 'en-US,en;q=0.8'),
		]

		opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)) #),RHandler()


		opener.addheaders = hdrs

		response = None

		request = urllib.request.Request(link)

		try:
			response = opener.open(request)

			olink = link
			for i in range(0, _MAX_REDIRECTS): # i have no idea of this is something I should be doing.
				if olink == response.geturl():
					break
				else:
					print("Following redirect to: {0}".format(response.geturl()))
					response = opener.open(urllib.request.Request(response.geturl()))

					olink = response.geturl()

		except Exception as e:
			print("Error downloading: " + link)
			traceback.print_exc()
			f.close()

			exit()

		headers = str(response.info())
		length = re.search(r'Content-Length: ([0-9]+)', headers, re.IGNORECASE)

		fileSize = None
		if length == None:
			pass #tbd
		else:
			fileSize = int(length.groups()[0])

		#fileSizeDigits = int(math.log10(fileSize))+1

		downloadedBytes = 0

		start = time.clock()

		fancyFileSize = None
		if fileSize != None:
			fancyFileSize = sizeof_fmt(fileSize)
			fancyFileSize = fancyFileSize.ljust(len(fancyFileSize))

		isGzipped = False
		if "content-encoding" in response.headers:
			if response.headers["content-encoding"] == "gzip":
				isGzipped = True

		while True:
			chunk = response.read(_CHUNKSIZE)
			downloadedBytes += len(chunk)
			if isGzipped:
				if len(chunk):
					try:
						chunk = zlib.decompress(chunk, 15+32)
					except Exception as e:
						print(e)
						exit()

			f.write(chunk)
			if fileSize != None:
				done = int(50 * downloadedBytes / fileSize)
				fancySpeed = sizeof_fmt((downloadedBytes//(time.clock() - start))/8,"B/s").rjust(5, ' ')
				fancyDownloadedBytes = sizeof_fmt(downloadedBytes).rjust(len(fancyFileSize), ' ')
				print("[{0}] - {1}/{2} ({3})".format( '|' * done + '-' * (50-done), fancyDownloadedBytes,fancyFileSize,fancySpeed), end= "\r")
			else:
				print("{0}".format( sizeof_fmt(downloadedBytes) ), end="\r")

			if not len(chunk):
				break
		print("")

		response.close()

		f.close()
		#print("File fully downloaded to:",fname)

		return os.path.basename(link)
	#:

	def download_file_v2(url=None, outputFileName=None, outputPath=None, bytes=False ):
		if not url:
			raise Exception('No url')
		if outputPath is None:
			outputPath = os.getcwd()
		else:
			if not os.path.isdir(outputPath):
				raise Exception('Path "" does not exist'.format(outputPath))
		fileName =  url.split('/')[-1] #base fallback name
		print("Connecting to: " + url)
		req = requests.get(url, stream=True, headers = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:57.0) Gecko/20100101 Firefox/57.0'})
		if req.status_code != 404:
			if 'content-disposition' in req.headers:
				fileName = req.headers['content-disposition']
			size = None
			if 'Content-Length' in req.headers:
				size = int(req.headers['Content-Length'])

			if 'Content-Encoding' in req.headers:
				if req.headers['Content-Encoding'] == "gzip":
					size = None

			print("Downloading: '{0}' {1}".format(url, fmt_size(size) if size!=None else "?" ))
			widgetsNoSize = [
				progressbar.Percentage(), " ",
				progressbar.Bar(fill=chr(9617), marker=chr(9608), left="[", right="]"), " ",
				progressbar.DataSize(),
			]
			widgets = [
				progressbar.Percentage(), " ",
				progressbar.Bar(fill=chr(9617), marker=chr(9608), left="[", right="]"), " ",
				progressbar.DataSize(), "/", progressbar.DataSize(variable="max_value"), " |",
				progressbar.AdaptiveTransferSpeed(), " | ",
				progressbar.ETA(),
			]
			pbar = None
			if size == None:
				pbar = progressbar.ProgressBar(widgets=widgetsNoSize,maxval=progressbar.UnknownLength)
			else:
				pbar = progressbar.ProgressBar(widgets=widgets,maxval=size)
			if outputFileName != None:
				fileName = outputFileName
			fullOutputPath = os.path.join(outputPath,fileName)

			if bytes == True:
				output = b''
				bytesrecv = 0
				pbar.start()
				for buffer in req.iter_content(chunk_size=1024):
					if buffer:
						 output += buffer
					pbar.update(bytesrecv)
					bytesrecv += len(buffer)
				pbar.finish()
				return output
			else:
				with open(fullOutputPath, "wb") as file:
					bytesrecv = 0
					pbar.start()
					for buffer in req.iter_content(chunk_size=1024):
						if buffer:
							file.write(buffer)
							file.flush()
						pbar.update(bytesrecv)
						bytesrecv += len(buffer)
					pbar.finish()

					return fullOutputPath
	#:

	def run_process(self,command,ignoreErrors = False, exitOnError = True):
		isSvn = False
		if not isinstance(command, str):
			command = " ".join(command) # could fail I guess
		if command.lower().startswith("svn"):
			isSvn = True
		self.logger.debug("Running '{0}' in '{1}'".format(command,os.getcwd()))
		process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
		while True:
			nextline = process.stdout.readline()
			if nextline == b'' and process.poll() is not None:
				break
			if isSvn:
				if not nextline.decode('utf-8').startswith('A    '):
					if self.quietMode == True:
						self.buildLogFile.write(nextline.decode('utf-8','replace'))
					else:
						sys.stdout.write(nextline.decode('utf-8','replace'))
						sys.stdout.flush()
			else:
				if self.quietMode == True:
					self.buildLogFile.write(nextline.decode('utf-8','replace'))
				else:
					sys.stdout.write(nextline.decode('utf-8','replace'))
					sys.stdout.flush()

		return_code = process.returncode
		output = process.communicate()[0]
		process.wait()
		if (return_code == 0):
			return output
		else:
			if ignoreErrors:
				return output
			self.logger.error("Error [{0}] running process: '{1}' in '{2}'".format(return_code,command,os.getcwd()))
			self.logger.error("You can try deleting the product/dependency folder: '{0}' and re-run the script".format(os.getcwd()))
			if self.quietMode:
				self.logger.error("Please check the raw_build.log file")
			if exitOnError:
				exit(1)

		#p = subprocess.Popen(command, stdout=subprocess.PIPE,stderr=subprocess.STDOUT, universal_newlines = True, shell = True)
		#for line in iter(p.stdout.readline, b''):
		#	sys.stdout.write(line)
		#	sys.stdout.flush()
		#p.close()

	def get_process_result(self,command):
		if not isinstance(command, str):
			command = " ".join(command) # could fail I guess
		process = subprocess.Popen(command, stdout=subprocess.PIPE, universal_newlines=True, shell=True)
		out = process.stdout.readline().rstrip("\n").rstrip("\r")
		process.stdout.close()
		return_code = process.wait()
		if (return_code == 0):
			return out
		else:
			self.logger.error("Error [%d] creating process '%s'" % (return_code,command))
			exit()

	def sanitize_filename(self,f):
		return re.sub(r'[/\\:*?"<>|]', '', f)

	def md5(self,*args):
		msg = ''.join(args).encode("utf-8")
		m = hashlib.md5()
		m.update(msg)
		return m.hexdigest()

	def hash_file(self,fname,type = "sha256"):
		hash = None
		if type == "sha256":
			hash = hashlib.sha256()
		elif type == "sha512":
			hash = hashlib.sha512()
		elif type == "md5":
			hash = hashlib.md5()
		elif type == "blake2b":
			hash = hashlib.blake2b()
		with open(fname, "rb") as f:
			for chunk in iter(lambda: f.read(4096), b""):
				hash.update(chunk)
		return hash.hexdigest()

	def touch(self,f):
		Path(f).touch()

	def chmodpux(self,file):
		st = os.stat(file)
		os.chmod(file, st.st_mode | stat.S_IXUSR) #S_IEXEC would be just +x
	#:

	def mercurial_clone(self,url,virtFolderName=None,renameTo=None,desiredBranch=None):
		if virtFolderName == None:
			virtFolderName = self.sanitize_filename(os.path.basename(url))
			if not virtFolderName.endswith(".hg"): virtFolderName += ".hg"
			virtFolderName = virtFolderName.replace(".hg","_hg")
		else:
			virtFolderName = self.sanitize_filename(virtFolderName)

		realFolderName = virtFolderName
		if renameTo != None:
			realFolderName = renameTo

		branchString = ""
		if desiredBranch != None:
			branchString = " {0}".format( desiredBranch )

		if os.path.isdir(realFolderName):
			self.cchdir(realFolderName)
			hgVersion = subprocess.check_output('hg --debug id -i', shell=True)
			self.run_process('hg pull -u')
			self.run_process('hg update -C{0}'.format(" default" if desiredBranch == None else branchString))
			hgVersionNew = subprocess.check_output('hg --debug id -i', shell=True)
			if hgVersion != hgVersionNew:
				self.logger.debug("HG clone has code changes, updating")
				self.removeAlreadyFiles()
			else:
				self.logger.debug("HG clone already up to date")
			self.cchdir("..")
		else:
			self.logger.info("HG cloning '%s' to '%s'" % (url,realFolderName))
			self.run_process('hg clone {0} {1}'.format(url,realFolderName + ".tmp" ))
			if desiredBranch != None:
				self.cchdir(realFolderName + ".tmp")
				self.logger.debug("HG updating to:{0}".format(" master" if desiredBranch == None else branchString))
				self.run_process('hg up{0} -v'.format("" if desiredBranch == None else branchString))
				self.cchdir("..")
			self.run_process('mv "{0}" "{1}"'.format(realFolderName + ".tmp", realFolderName))
			self.logger.info("Finished HG cloning '%s' to '%s'" % (url,realFolderName))

		return realFolderName
	#:
	def git_clone(self,url,virtFolderName=None,renameTo=None,desiredBranch=None,recursive=False,doNotUpdate=False,desiredPR=None):
		if virtFolderName == None:
			virtFolderName = self.sanitize_filename(os.path.basename(url))
			if not virtFolderName.endswith(".git"): virtFolderName += ".git"
			virtFolderName = virtFolderName.replace(".git","_git")
		else:
			virtFolderName = self.sanitize_filename(virtFolderName)

		realFolderName = virtFolderName
		if renameTo != None:
			realFolderName = renameTo

		branchString = ""
		if desiredBranch != None:
			branchString = " {0}".format( desiredBranch )

		properBranchString = "master"
		if desiredBranch != None:
			properBranchString  = desiredBranch

		if os.path.isdir(realFolderName):
			if desiredPR != None:
				self.logger.warning("####################")
				self.logger.info("Git repositiories with set PR will not auto-update, please delete the repo and retry to do so.")
				self.logger.warning("####################")
			elif doNotUpdate == True:
				self.logger.info("####################")
				self.logger.info("do_not_git_update == true")
				self.logger.info("####################")
			else:
				self.cchdir(realFolderName)

				self.run_process('git remote update')

				UPSTREAM = '@{u}' # or branchName i guess
				if desiredBranch != None:
					UPSTREAM = properBranchString
				LOCAL    = subprocess.check_output('git rev-parse @',shell=True).decode("utf-8")
				REMOTE   = subprocess.check_output('git rev-parse "{0}"'.format(UPSTREAM),shell=True).decode("utf-8")
				BASE     = subprocess.check_output('git merge-base @ "{0}"'.format(UPSTREAM),shell=True).decode("utf-8")

				self.run_process('git checkout -f')
				self.run_process('git checkout {0}'.format(properBranchString))

				if LOCAL == REMOTE:
					self.logger.debug("####################")
					self.logger.debug("Up to date")
					self.logger.debug("LOCAL:  " + LOCAL)
					self.logger.debug("REMOTE: " + REMOTE)
					self.logger.debug("BASE:   " + BASE)
					self.logger.debug("####################")
				elif LOCAL == BASE:
					self.logger.debug("####################")
					self.logger.debug("Need to pull")
					self.logger.debug("LOCAL:  " + LOCAL)
					self.logger.debug("REMOTE: " + REMOTE)
					self.logger.debug("BASE:   " + BASE)
					self.logger.debug("####################")
					if desiredBranch != None:
						#bsSplit = properBranchString.split("/")
						#if len(bsSplit) == 2:
						#	self.run_process('git pull origin {1}'.format(bsSplit[0],bsSplit[1]))
						#else:
						self.run_process('git pull origin {0}'.format(properBranchString))
					else:
						self.run_process('git pull'.format(properBranchString))
					self.run_process('git clean -xfdf') #https://gist.github.com/nicktoumpelis/11214362
					self.run_process('git submodule foreach --recursive git clean -xfdf')
					self.run_process('git reset --hard')
					self.run_process('git submodule foreach --recursive git reset --hard')
					self.run_process('git submodule update --init --recursive')
				elif REMOTE == BASE:
					self.logger.debug("####################")
					self.logger.debug("need to push")
					self.logger.debug("LOCAL:  " + LOCAL)
					self.logger.debug("REMOTE: " + REMOTE)
					self.logger.debug("BASE:   " + BASE)
					self.logger.debug("####################")
				else:
					self.logger.debug("####################")
					self.logger.debug("diverged?")
					self.logger.debug("LOCAL:  " + LOCAL)
					self.logger.debug("REMOTE: " + REMOTE)
					self.logger.debug("BASE    " + BASE)
					self.logger.debug("####################")
				self.cchdir("..")
		else:
			recur = ""
			if recursive:
				recur = " --recursive"
			self.logger.info("GIT cloning '%s' to '%s'" % (url,os.getcwd() +"/"+ realFolderName))
			self.run_process('git clone{0} --progress "{1}" "{2}"'.format(recur,url,realFolderName + ".tmp" ))
			if desiredBranch != None:
				self.cchdir(realFolderName + ".tmp")
				self.logger.debug("GIT Checking out:{0}".format(" master" if desiredBranch == None else branchString))
				self.run_process('git checkout{0}'.format(" master" if desiredBranch == None else branchString))
				self.cchdir("..")
			if desiredPR != None:
				self.cchdir(realFolderName + ".tmp")
				self.logger.info("GIT Fetching PR: {0}".format(desiredPR))
				self.run_process('git fetch origin refs/pull/{0}/head'.format(desiredPR))
				self.cchdir("..")
			self.run_process('mv "{0}" "{1}"'.format(realFolderName + ".tmp", realFolderName))
			self.logger.info("Finished GIT cloning '%s' to '%s'" % (url,realFolderName))

		return realFolderName
	#:
	def svn_clone(self, url, dir, desiredBranch = None): # "branch".. "clone"..
		dir = self.sanitize_filename(dir)
		if not dir.endswith("_svn"): dir += "_svn"

		if not os.path.isdir(dir):
			self.logger.info("SVN checking out to %s" % (dir))
			if desiredBranch == None:
				self.run_process('svn co "%s" "%s.tmp" --non-interactive --trust-server-cert' % (url,dir))
			else:
				self.run_process('svn co -r "%s" "%s" "%s.tmp" --non-interactive --trust-server-cert' % (desiredBranch,url,dir))
			shutil.move('%s.tmp' % dir, dir)
		else:
			pass
			#svn up?
		return dir
	#:
	def verify_hash(self,file,hash):
		if hash["type"] not in ["sha256","sha512","md5","blake2b"]:
			raise Exception("Unsupported hash type: " + hash["type"])
		newHash = self.hash_file(file,hash["type"])
		if hash["sum"] == newHash:
			return (True,hash["sum"],newHash)
		return (False,hash["sum"],newHash)

	def download_unpack_file(self,data,folderName = None,workDir = None):
		customFolder = False
		if folderName == None:
			folderName = os.path.basename(os.path.splitext(urlparse(self.get_primary_package_url(data)).path)[0]).rstrip(".tar")
		else:
			customFolder = True
		folderToCheck = folderName
		if workDir != None:
			folderToCheck = workDir

		if not os.path.isfile(os.path.join(folderToCheck,"unpacked.successfully")):
			dl_loc = self.get_best_mirror(data)
			url = dl_loc["url"]
			fileName = os.path.basename(urlparse(url).path)
			self.logger.info("Downloading {0} ({1})".format( fileName, url ))

			self.download_file(url,fileName)


			if "hashes" in dl_loc:
				if len(dl_loc["hashes"]) >= 1:
					for hash in dl_loc["hashes"]:
						self.logger.info("Comparing hashes..")
						hashReturn = self.verify_hash(fileName,hash)
						if hashReturn[0] == True:
							self.logger.info("Hashes matched: {0}...{1} (local) == {2}...{3} (remote)".format(hashReturn[1][0:5],hashReturn[1][-5:],hashReturn[2][0:5],hashReturn[2][-5:]))
						else:
							self.logger.error("File hashes didn't match: %s(local) != %s(remote)" % (hashReturn[1],hashReturn[2]))
							raise Exception("File download error: Hash mismatch")
							exit(1)

			self.logger.info("Unpacking {0}".format( fileName ))

			tars = (".gz",".bz2",".xz",".bz",".tgz") # i really need a better system for this.. but in reality, those are probably the only formats we will ever encounter.

			customFolderTarArg = ""

			if customFolder:
				customFolderTarArg = ' -C "' + folderName + '" --strip-components 1'
				os.makedirs(folderName)

			if fileName.endswith(tars):
				self.run_process('tar -xf "{0}"{1}'.format( fileName, customFolderTarArg ))
			else:
				self.run_process('unzip "{0}"'.format( fileName ))

			self.touch(os.path.join(folderName,"unpacked.successfully"))

			os.remove(fileName)

			return folderName

		else:
			self.logger.debug("{0} already downloaded".format( folderName ))
			return folderName
	#:

	def check_mirrors(self,dl_locations):
		for loc in dl_locations:
			userAgent = self.userAgent
			if 'sourceforge.net' in loc["url"].lower():
				userAgent = 'wget/1.18' # sourceforce <3 wget
			try:
				req = requests.request("GET", loc["url"], stream=True, allow_redirects=True, headers = { "User-Agent": self.userAgent } )
			except requests.exceptions.RequestException as e:
				self.logger.debug(e)
			else:
				if req.status_code == 200:
					return loc
				else:
					self.logger.debug(loc["url"] + " unable to reach: HTTP" + str(req.status_code))

		return dl_locations[0] # return the first if none could be found.

	def get_best_mirror(self,data): #returns the best online mirror of a file, and its hash.
		if "url" in data:
			self.logger.warning("Package has the old URL format, please update it.")
			return { "url" : data["url"], "hashes" : [] }
		elif "download_locations" not in data:
			raise Exception("download_locations not specificed for package: " + name)
		else:
			if not len(data["download_locations"]) >= 1:
				raise Exception("download_locations is empty for package: " + name)
			if "url" not in data["download_locations"][0]:
				raise Exception("download_location #1 of package '%s' has no url specified" % (name))

			return self.check_mirrors(data["download_locations"])

	def get_primary_package_url(self,data): # returns the URL of the first download_locations entry from a package, unlike get_best_mirror this one ignores the old url format
		if "url" in data:
			self.logger.debug("Package has the old URL format, please update it.")
			return data["url"]
		elif "download_locations" not in data:
			raise Exception("download_locations not specificed")
		else:
			if not len(data["download_locations"]) >= 1:
				raise Exception("download_locations is empty for package")
			if "url" not in data["download_locations"][0]:
				raise Exception("download_location #1 of package has no url specified")
			return data["download_locations"][0]["url"] #TODO: do not assume correct format
	#:

	def get_thing_path(self,name,data,type): # type = PRODUCT or DEPENDENCY
		outPath = os.getcwd()
		workDir = None
		renameFolder = None
		if 'rename_folder' in data:
			if data['rename_folder'] != None:
				renameFolder = data['rename_folder']
		if type == "P":
			outPath = os.path.join(outPath,self.bitnessDir + "_products")
			self.cchdir(self.bitnessDir + "_products")
		else:
			outPath = os.path.join(outPath,self.bitnessDir)
			self.cchdir(self.bitnessDir)

		if data["repo_type"] == "git":
			branch     = self.getValueOrNone(data,'branch')
			recursive  = self.getValueOrNone(data,'recursive_git')
			folderName = self.getValueOrNone(data,'folder_name')
			doNotUpdate = False
			if 'do_not_git_update' in data:
				if data['do_not_git_update'] == True:
					doNotUpdate=True
			workDir    = self.git_clone(self.get_primary_package_url(data),folderName,renameFolder,branch,recursive,doNotUpdate)
		if data["repo_type"] == "svn":
			workDir = self.svn_clone(self.get_primary_package_url(data),data["folder_name"],renameFolder)
		if data['repo_type'] == 'mercurial':
			branch = self.getValueOrNone(data,'branch')
			workDir = self.mercurial_clone(self.get_primary_package_url(data),self.getValueOrNone(data,'folder_name'),renameFolder,branch)
		if data["repo_type"] == "archive":
			if "folder_name" in data:
				workDir = self.download_unpack_file(data,data["folder_name"],workDir)
			else:
				workDir = self.download_unpack_file(data,None,workDir)

		if workDir == None:
			print("Unexpected error when building {0}, please report this:".format(name), sys.exc_info()[0])
			raise

		if 'rename_folder' in data: # this should be moved inside the download functions, TODO.. but lazy
			if data['rename_folder'] != None:
				if not os.path.isdir(data['rename_folder']):
					shutil.move(workDir, data['rename_folder'])
				workDir = data['rename_folder']
		self.cchdir("..")
		return os.path.join(outPath,workDir)

	def build_thing(self,name,data,type,force_rebuild = False, skipDepends = False): # type = PRODUCT or DEPENDENCY # I couldn't come up with a better name :S
		#we are in workdir
		if '_already_built' in data:
			if data['_already_built'] == True:
				return
		if self.debugMode:
			for tk in os.environ:
				print("############ " + tk + " : " + os.environ[tk])

		if 'skip_deps' in data:
			if data['skip_deps'] == True:
				skipDepends = True
		if "depends_on" in data and skipDepends == False: #dependception
			if len(data["depends_on"])>0:
				self.logger.info("Building dependencies of '%s'" % (name))
				for libraryName in data["depends_on"]:
					if libraryName not in self.DEPENDS:
						raise MissingDependency("The dependency '{0}' of '{1}' does not exist in dependency config.".format( libraryName, name)) #sys.exc_info()[0]
					else:
						self.build_thing(libraryName,self.DEPENDS[libraryName],"DEPENDENCY")
		if 'is_dep_inheriter' in data:
			if data['is_dep_inheriter'] == True:
				return

		self.logger.info("Building {0} '{1}'".format(type.lower(),name))
		self.defaultCFLAGS()

		if 'warnings' in data:
			if len(data['warnings']) > 0:
				for w in data['warnings']:
					self.logger.warning(w)

		workDir = None
		renameFolder = None
		if 'rename_folder' in data:
			if data['rename_folder'] != None:
				renameFolder = data['rename_folder']

		if type == "PRODUCT":
			self.cchdir(self.bitnessDir + "_products") #descend into x86_64_products
		else:
			self.cchdir(self.bitnessDir) #descend into x86_64

		if data["repo_type"] == "git":
			branch     = self.getValueOrNone(data,'branch')
			recursive  = self.getValueOrNone(data,'recursive_git')
			folderName = self.getValueOrNone(data,'folder_name')
			doNotUpdate = False
			if 'do_not_git_update' in data:
				if data['do_not_git_update'] == True:
					doNotUpdate=True
			desiredPRVal = None
			if 'desired_pr_id' in data:
				if data['desired_pr_id'] != None:
					desiredPRVal = data['desired_pr_id']
			workDir = self.git_clone(self.get_primary_package_url(data),folderName,renameFolder,branch,recursive,doNotUpdate,desiredPR=desiredPRVal)
		elif data["repo_type"] == "svn":
			workDir = self.svn_clone(self.get_primary_package_url(data),data["folder_name"],renameFolder)
		elif data['repo_type'] == 'mercurial':
			branch = self.getValueOrNone(data,'branch')
			workDir = self.mercurial_clone(self.get_primary_package_url(data),self.getValueOrNone(data,'folder_name'),renameFolder,branch)
		elif data["repo_type"] == "archive":
			if "folder_name" in data:
				workDir = self.download_unpack_file(data,data["folder_name"],workDir)
			else:
				workDir = self.download_unpack_file(data,None,workDir)
		elif data["repo_type"] == "none":
			if "folder_name" in data:
				workDir = data["folder_name"]
				os.makedirs(workDir, exist_ok=True)
			else:
				print("Error: When using repo_type 'none' you have to set folder_name as well.")
				exit(1)

		if workDir == None:
			print("Unexpected error when building {0}, please report this:".format(name), sys.exc_info()[0])
			raise

		if 'rename_folder' in data: # this should be moved inside the download functions, TODO.. but lazy
			if data['rename_folder'] != None:
				if not os.path.isdir(data['rename_folder']):
					shutil.move(workDir, data['rename_folder'])
				workDir = data['rename_folder']

		if 'download_header' in data:
			if data['download_header'] != None:
				for h in data['download_header']:
					self.downloadHeader(h)

		self.cchdir(workDir) #descend into x86_64/[DEPENDENCY_OR_PRODUCT_FOLDER]
		if 'debug_downloadonly' in data:
			self.cchdir("..")
			exit()

		oldPath = self.getKeyOrBlankString(os.environ,"PATH")
		currentFullDir = os.getcwd()

		if not self.anyFileStartsWith('already_configured'):
			if 'run_pre_patch' in data:
				if data['run_pre_patch'] != None:
					for cmd in data['run_pre_patch']:
						cmd = self.replaceVariables(cmd)
						self.logger.debug("Running pre-patch-command: '{0}'".format( cmd ))
						self.run_process(cmd)

		if 'source_subfolder' in data:
			if data['source_subfolder'] != None:
				if not os.path.isdir(data['source_subfolder']):
					os.makedirs(data['source_subfolder'], exist_ok=True)
				self.cchdir(data['source_subfolder'])

		if force_rebuild:
			self.removeAlreadyFiles()
			self.removeConfigPatchDoneFiles()
			if os.path.isdir(".git"):
				self.run_process('git clean -xfdf') #https://gist.github.com/nicktoumpelis/11214362
				self.run_process('git submodule foreach --recursive git clean -xfdf')
				self.run_process('git reset --hard')
				self.run_process('git submodule foreach --recursive git reset --hard')
				self.run_process('git submodule update --init --recursive')

		if 'debug_confighelp_and_exit' in data:
			if data['debug_confighelp_and_exit'] == True:
				self.bootstrap_configure()
				self.run_process("./configure --help")
				exit()

		if 'cflag_addition' in data:
			if data['cflag_addition'] != None:
				self.logger.debug("Adding '{0}' to CFLAGS".format( data['cflag_addition'] ))
				os.environ["CFLAGS"] = os.environ["CFLAGS"] + " " + data['cflag_addition']

		if 'custom_cflag' in data:
			if data['custom_cflag'] != None:
				self.logger.debug("Setting CFLAGS to '{0}'".format( data['custom_cflag'] ))
				os.environ["CFLAGS"] = data['custom_cflag']
				os.environ["LDFLAGS"] = data['custom_cflag']

		if 'custom_path' in data:
			if data['custom_path'] != None:
				self.logger.debug("Setting PATH to '{0}'".format( self.replaceVariables(data['custom_path']) ))
				os.environ["PATH"] = self.replaceVariables(data['custom_path'])

		if 'flipped_path' in data:
			if data['flipped_path'] == True:
				bef = os.environ["PATH"]
				os.environ["PATH"] = "{0}:{1}:{2}".format ( self.mingwBinpath, os.path.join(self.targetPrefix,'bin'), self.originalPATH ) #todo properly test this..
				self.logger.debug("Flipping path to: '{0}' from '{1}'".format(bef,os.environ["PATH"]))

		if 'env_exports' in data:
			if data['env_exports'] != None:
				for key,val in data['env_exports'].items():
					val = self.replaceVariables(val)
					prevEnv = ''
					if key in os.environ:
						prevEnv = os.environ[key]
					self.logger.debug("Environment variable '{0}' has been set from {1} to '{2}'".format( key, prevEnv, val ))
					os.environ[key] = val

		if 'patches' in data:
			if data['patches'] != None:
				for p in data['patches']:
					self.apply_patch(p[0],p[1],False,self.getValueByIntOrNone(p,2))

		if not self.anyFileStartsWith('already_ran_make'):
			if 'run_post_patch' in data:
				if data['run_post_patch'] != None:
					for cmd in data['run_post_patch']:
						if cmd.startswith("!SWITCHDIR"):
							self.cchdir("|".join(cmd.split("|")[1:]))
						else:
							cmd = self.replaceVariables(cmd)
							self.logger.debug("Running post-patch-command: '{0}'".format( cmd ))
							self.run_process(cmd)

		conf_system = "autoconf"
		build_system = "make"
		
		# conf_system_specifics = {
			# "gnumake_based_systems" : [ "cmake", "autoconf" ],
			# "ninja_based_systems" : [ "meson" ]
		# }
		
		if 'build_system' in data:                 # Kinda redundant, but ill keep it for now, maybe add an alias system for this.
			if data['build_system'] == "ninja":    #
				build_system = "ninja"             #
			if data['build_system'] == "waf":      #
				build_system = "waf"               #
			if data['build_system'] == "rake":     #
				build_system = "rake"              #
		if 'conf_system' in data:                  #
			if data['conf_system'] == "cmake":     #
				conf_system = "cmake"              #
			elif data['conf_system'] == "meson":   #
				conf_system = "meson"              #
			elif data['conf_system'] == "waf":     #
				conf_system = "waf"                #
			
		needs_conf = True
			
		if 'needs_configure' in data:
			if data['needs_configure'] == False:
				needs_conf = False
		
		if needs_conf:
			if conf_system == "cmake":
				self.cmake_source(name,data)
			elif conf_system == "meson":
				self.create_meson_environment_file()
				self.meson_source(name,data)
			else:
				self.configure_source(name,data,conf_system)

		if 'patches_post_configure' in data:
			if data['patches_post_configure'] != None:
				for p in data['patches_post_configure']:
					self.apply_patch(p[0],p[1],True)

		if 'make_subdir' in data:
			if data['make_subdir'] != None:
				if not os.path.isdir(data['make_subdir']):
					os.makedirs(data['make_subdir'], exist_ok=True)
				self.cchdir(data['make_subdir'])

		if 'needs_make' in data:
			if data['needs_make'] == True:
				self.build_source(name,data,build_system)
		else:
			self.build_source(name,data,build_system)
		
		if 'needs_make_install' in data:
			if data['needs_make_install'] == True:
				self.install_source(name,data,build_system)
		else:
			self.install_source(name,data,build_system)


		if 'env_exports' in data:
			if data['env_exports'] != None:
				for key,val in data['env_exports'].items():
					self.logger.debug("Environment variable '{0}' has been UNSET!".format( key, val ))
					del os.environ[key]

		if 'flipped_path' in data:
			if data['flipped_path'] == True:
				bef = os.environ["PATH"]
				os.environ["PATH"] = "{0}:{1}".format ( self.mingwBinpath, self.originalPATH )
				self.logger.debug("Resetting flipped path to: '{0}' from '{1}'".format(bef,os.environ["PATH"]))

		if 'source_subfolder' in data:
			if data['source_subfolder'] != None:
				if not os.path.isdir(data['source_subfolder']):
					os.makedirs(data['source_subfolder'], exist_ok=True)
				self.cchdir(currentFullDir)

		if 'make_subdir' in data:
			if data['make_subdir'] != None:
				self.cchdir(currentFullDir)

		self.cchdir("..") #asecond into x86_64
		if type == "PRODUCT":
			self.PRODUCTS[name]["_already_built"] = True
		else:
			self.DEPENDS[name]["_already_built"] = True

		self.logger.info("Building {0} '{1}': Done!".format(type.lower(),name))
		if 'debug_exitafter' in data:
			exit()

		if 'custom_path' in data:
			if data['custom_path'] != None:
				self.logger.debug("Re-setting PATH to '{0}'".format( oldPath ))
				os.environ["PATH"] = oldPath

		self.defaultCFLAGS()
		self.cchdir("..") #asecond into workdir
	#:
	def bootstrap_configure(self):
		if not os.path.isfile("configure"):
			if os.path.isfile("bootstrap.sh"):
				self.run_process('./bootstrap.sh')
			elif os.path.isfile("autogen.sh"):
				self.run_process('./autogen.sh')
			elif os.path.isfile("buildconf"):
				self.run_process('./buildconf')
			elif os.path.isfile("bootstrap"):
				self.run_process('./bootstrap')
			elif os.path.isfile("bootstrap"):
				self.run_process('./bootstrap')
			elif os.path.isfile("configure.ac"):
				self.run_process('autoreconf -fiv')

	def configure_source(self,name,data,conf_system):
		touch_name = "already_configured_%s" % (self.md5(name,self.getKeyOrBlankString(data,"configure_options")))
		
		if not os.path.isfile(touch_name):
			self.removeAlreadyFiles()
			self.removeConfigPatchDoneFiles()

			doBootStrap = True
			if 'do_not_bootstrap' in data:
				if data['do_not_bootstrap'] == True:
					doBootStrap = False
			
			if doBootStrap:
				if conf_system == "waf":
					if not os.path.isfile("waf"):
						if os.path.isfile("bootstrap.py"):
							self.run_process('./bootstrap.py')
				else:
					self.bootstrap_configure()

			configOpts = ''
			if 'configure_options' in data:
				configOpts = self.replaceVariables(data["configure_options"])
			self.logger.info("Configuring '{0}' with: {1}".format(name, configOpts ),extra={'type': conf_system})

			confCmd = './configure'
			if conf_system == "waf":
				confCmd = './waf --color=yes configure'
			elif 'configure_path' in data:
				if data['configure_path'] != None:
					confCmd = data['configure_path']

			self.run_process('{0} {1}'.format(confCmd, configOpts))

			if 'run_post_configure' in data:
				if data['run_post_configure'] != None:
					for cmd in data['run_post_configure']:
						cmd = self.replaceVariables(cmd)
						self.logger.info("Running post-configure-command: '{0}'".format( cmd ))
						self.run_process(cmd)

			doClean = True
			if 'clean_post_configure' in data:
				if data['clean_post_configure'] == False:
					doClean = False

			if doClean:
				mCleanCmd = 'make clean'
				if conf_system == "waf":
					mCleanCmd = './waf --color=yes clean'
				self.run_process('{0} -j {1}'.format( mCleanCmd, self.cpuCount ),True)

			self.touch(touch_name)

	def apply_patch(self,url,type = "-p1", postConf = False, folderToPatchIn = None):

		originalFolder = os.getcwd()

		if folderToPatchIn != None:
			self.cchdir(folderToPatchIn)
			self.logger.info("Moving to patch folder: {0}" .format( os.getcwd() ))

		fileName = os.path.basename(urlparse(url).path)

		if not os.path.isfile(fileName):
			self.logger.info("Downloading patch '{0}' to: {1}".format( url, fileName ))
			self.download_file(url,fileName)

		patch_touch_name = "%s.done" % (fileName)

		ignoreErr = False
		exitOn = True
		ignore = ""

		if postConf:
			patch_touch_name = patch_touch_name + "_past_conf"
			ignore = "-N "
			ignoreErr = True
			exitOn = False

		if not os.path.isfile(patch_touch_name):
			self.logger.info("Patching source using: '{0}'".format( fileName ))
			self.run_process('patch {2}{0} < "{1}"'.format(type, fileName, ignore ),ignoreErr,exitOn)
			self.touch(patch_touch_name)
			if not postConf:
				self.removeAlreadyFiles()
		else:
			self.logger.debug("Patch '{0}' already applied".format( fileName ))

		if folderToPatchIn != None:
			self.cchdir(originalFolder)
	#:
	
	def meson_source(self,name,data):
		touch_name = "already_ran_meson_%s" % (self.md5(name,self.getKeyOrBlankString(data,"configure_options	")))

		if not os.path.isfile(touch_name):
			self.removeAlreadyFiles()

			makeOpts = ''
			if 'configure_options' in data:
				makeOpts = self.replaceVariables(data["configure_options"])
			self.logger.info("Meson'ing '{0}' with: {1}".format( name, makeOpts ))

			self.run_process('meson {0}'.format( makeOpts ))

			self.touch(touch_name)

	def cmake_source(self,name,data):
		touch_name = "already_ran_cmake_%s" % (self.md5(name,self.getKeyOrBlankString(data,"configure_options")))

		if not os.path.isfile(touch_name):
			self.removeAlreadyFiles()

			makeOpts = ''
			if 'configure_options' in data:
				makeOpts = self.replaceVariables(data["configure_options"])
			self.logger.info("C-Making '{0}' with: {1}".format( name, makeOpts ))

			self.run_process('cmake {0}'.format( makeOpts ))

			self.run_process("make clean",True)

			self.touch(touch_name)

	def build_source(self,name,data,build_system):
		touch_name = "already_ran_make_%s" % (self.md5(name,self.getKeyOrBlankString(data,"build_options")))
		if not os.path.isfile(touch_name):
			mkCmd = 'make'
			
			if build_system == "waf":
				mkCmd = './waf --color=yes'
			if build_system == "rake":
				mkCmd = 'rake'
			if build_system == "ninja":
				mkCmd = 'ninja'
			
			if build_system == "make":
				if os.path.isfile("configure"):
					self.run_process('{0} clean -j {1}'.format( mkCmd, self.cpuCount ),True)

			makeOpts = ''
			if 'build_options' in data:
				makeOpts = self.replaceVariables(data["build_options"])

			self.logger.info("Building '{0}' with: {1} in {2}".format(name, makeOpts, os.getcwd()),extra={'type': build_system})

			cpcnt = '-j {0}'.format(self.cpuCount)

			if 'cpu_count' in data:
				if data['cpu_count'] != None:
					cpcnt = ""

			if 'ignore_build_fail_and_run' in data:
				if len(data['ignore_build_fail_and_run']) > 0: #todo check if its a list too
					try:
						if build_system == "waf":
							mkCmd = './waf --color=yes build'
						self.run_process('{0} {2} {1}'.format( mkCmd, cpcnt, makeOpts ))
					except Exception as e:
						self.logger.info("Ignoring failed make process...")
						for cmd in data['ignore_build_fail_and_run']:
							cmd = self.replaceVariables(cmd)
							self.logger.info("Running post-failed-make-command: '{0}'".format( cmd ))
							self.run_process(cmd)
			else:
				if build_system == "waf":
					mkCmd = './waf --color=yes build'
				self.run_process('{0} {2} {1}'.format( mkCmd, cpcnt, makeOpts ))

			if 'run_post_build' in data:
				if data['run_post_build'] != None:
					for cmd in data['run_post_build']:
						cmd = self.replaceVariables(cmd)
						self.logger.info("Running post-build-command: '{0}'".format( cmd ))
						self.run_process(cmd)

			self.touch(touch_name)

	def install_source(self,name,data,build_system):
		touch_name = "already_ran_install_%s" % (self.md5(name,self.getKeyOrBlankString(data,"install_options")))
		if not os.path.isfile(touch_name):
			cpcnt = '-j {0}'.format(self.cpuCount)

			if 'cpu_count' in data:
				if data['cpu_count'] != None:
					cpcnt = ""

			makeInstallOpts  = ''
			if 'install_options' in data:
				if data['install_options'] != None:
					makeInstallOpts = self.replaceVariables(data["install_options"])
			installTarget = "install"
			if 'install_target' in data:
				if data['install_target'] != None:
					installTarget = data['install_target']


			self.logger.info("Installing '{0}' with: {1}".format(name, makeInstallOpts ),extra={'type': build_system})

			mkCmd = "make"
			if build_system == "waf":
				mkCmd = "./waf"
			if build_system == "rake":
				mkCmd = "rake"	
			if build_system == "ninja":
				mkCmd = "ninja"

			self.run_process('{0} {1} {2} {3}'.format(mkCmd, installTarget, makeInstallOpts, cpcnt ))

			if 'run_post_install' in data:
				if data['run_post_install'] != None:
					for cmd in data['run_post_install']:
						cmd = self.replaceVariables(cmd)
						self.logger.info("Running post-install-command: '{0}'".format( cmd ))
						self.run_process(cmd)

			self.touch(touch_name)
	#:

	def defaultCFLAGS(self):
		self.logger.debug("Reset CFLAGS to: {0}".format( self.originalCflags ) )
		os.environ["CFLAGS"] = self.originalCflags
		os.environ["LDFLAGS"] = self.originalCflags
		os.environ["PKG_CONFIG_LIBDIR"] = ""
	#:

	def anyFileStartsWith(self,wild):
		for file in os.listdir('.'):
			if file.startswith(wild):
				return True
		return False

	def removeAlreadyFiles(self):
		for af in glob.glob("./already_*"):
			os.remove(af)
	#:

	def removeConfigPatchDoneFiles(self):
		for af in glob.glob("./*.diff.done_past_conf"):
			os.remove(af)
		for af in glob.glob("./*.patch.done_past_conf"):
			os.remove(af)
	#:
	def generateCflagString(self, prefix = ""):
		cfs = os.environ["CFLAGS"]
		cfs = cfs.split(' ')
		out = ''
		if len(cfs) >= 1:
			for c in cfs:
				out+=prefix + c + ' '
			out.rstrip(' ')
			return out
		return ''

	def replaceVariables(self,cmd):

		m = re.search(r'\!VAR\((.*)\)VAR!',cmd)
		if m != None:
			varName = m.groups()[0]
			if varName in self.VARIABLES:
				cmdReplacer = self.VARIABLES[varName]
				mr = re.sub(r"\!VAR\((.*)\)VAR!", r"{0}".format(cmdReplacer), cmd, flags=re.DOTALL)
				cmd = mr

		cmd = cmd.format(
			cmake_prefix_options       = self.cmakePrefixOptions,
			make_prefix_options        = self.makePrefixOptions,
			pkg_config_path            = self.pkgConfigPath,
			mingw_binpath              = self.mingwBinpath,
			mingw_binpath2             = self.mingwBinpath2,
			cross_prefix_bare          = self.bareCrossPrefix,
			cross_prefix_full          = self.fullCrossPrefix,
			target_prefix              = self.targetPrefix,
			inTreePrefix               = self.inTreePrefix,
			offtree_prefix             = self.offtreePrefix,
			target_host                = self.targetHost,
			target_sub_prefix          = self.targetSubPrefix,
			bit_name                   = self.bitnessDir,
			bit_name2                  = self.bitnessDir2,
			bit_name3                  = self.bitnessDir3,
			bit_name_win               = self.winBitnessDir,
			bit_num                    = self.currentBitness,
			product_prefix             = self.fullProductDir,
			target_prefix_sed_escaped = self.targetPrefix.replace("/","\\/"),
			make_cpu_count             = "-j {0}".format(self.cpuCount),
			original_cflags            = self.originalCflags,
			cflag_string               = self.generateCflagString('--extra-cflags='),
			current_path               = os.getcwd(),
			current_envpath            = self.getKeyOrBlankString(os.environ,"PATH"),
			meson_env_file             = self.mesonEnvFile
		)
		# needed actual commands sometimes, so I made this custom command support, comparable to "``" in bash, very very shady.. needs testing, but seems to work just flawlessly.

		m = re.search(r'\!CMD\((.*)\)CMD!',cmd)
		if m != None:
			cmdReplacer = subprocess.check_output(m.groups()[0], shell=True).decode("utf-8").replace("\n","").replace("\r","")
			mr = re.sub(r"\!CMD\((.*)\)CMD!", r"{0}".format(cmdReplacer), cmd, flags=re.DOTALL)
			cmd = mr
		return cmd
	#:
	def getValueOrNone(self,db,k):
		if k in db:
			if db[k] == None:
				return None
			else:
				return db[k]
		else:
			return None

	def getValueByIntOrNone(self,db,key):
		if key >= 0 and key < len(db):
			return db[key]
		else:
			return None


	def reReplaceInFile(self,infile,oldString,newString,outfile):
		with open(infile, 'rw') as f:
			for line in f:
				line = re.sub(oldString, newString, line)

	def getKeyOrBlankString(self,db,k):
		if k in db:
			if db[k] == None:
				return ""
			else:
				return db[k]
		else:
			return ""
	#:
	def cchdir(self,dir):
		if self.debugMode:
			print("Changing dir from {0} to {1}".format(os.getcwd(),dir))
		os.chdir(dir)

# ###################################################
# ################  PACKAGE CONFIGS  ################
# ###################################################

VARIABLES = {
	'ffmpeg_base_config' : # the base for all ffmpeg configurations.
		'--arch={bit_name2} '
		'--target-os=mingw32 '
		'--cross-prefix={cross_prefix_bare} '
		'--pkg-config=pkg-config '
		'--disable-w32threads '
		'--enable-cross-compile '
		'--enable-pic '
		'--enable-libsoxr '
		'--enable-libass '
		'--enable-iconv '
		'--enable-libtwolame '
		'--enable-libzvbi '
		'--enable-libcaca '
		'--enable-libmodplug '
		'--enable-cuvid '
		'--enable-libmp3lame '
		'--enable-version3 '
		'--enable-zlib '
		'--enable-librtmp '
		'--enable-libvorbis '
		'--enable-libtheora '
		'--enable-libspeex '
		'--enable-libgsm '
		'--enable-libopus '
		'--enable-bzlib '
		'--enable-libopencore-amrnb '
		'--enable-libopencore-amrwb '
		'--enable-libvo-amrwbenc '
		'--enable-libvpx '
		'--enable-libilbc '
		'--enable-libwavpack '
		'--enable-libwebp '
		'--enable-dxva2 '
		'--enable-avisynth '
		# '--enable-vapoursynth ' #maybe works?
		'--enable-gray '
		'--enable-libmysofa '
		'--enable-libflite '
		'--enable-lzma '
		'--enable-libsnappy '
		'--enable-libzimg '
		'--enable-libx264 '
		'--enable-libx265 '
		'--enable-libaom '
		'--enable-libdav1d '
		'--enable-frei0r '
		'--enable-filter=frei0r '
		'--enable-librubberband '
		'--enable-libvidstab '
		'--enable-libxavs '
		'--enable-libxvid '
		'--enable-libgme '
		'--enable-runtime-cpudetect '
		'--enable-libfribidi '
		'--enable-gnutls ' # nongpl: openssl,libtls(libressl)
		'--enable-gmp '
		'--enable-fontconfig '
		'--enable-libfontconfig '
		'--enable-libfreetype '
		'--enable-libbluray '
		'--enable-libcdio '
		'--enable-libmfx '
		'--disable-schannel '
		'--disable-gcrypt '
		#'--enable-libcodec2 ' # Requires https://github.com/traviscross/freeswitch/tree/master/libs/libcodec2, too lazy to split that off.
		'--enable-ladspa '
		'--enable-libxml2 '
		'--enable-libdavs2 '
		'--enable-libkvazaar '
		'--enable-libopenmpt '
		'--enable-libxavs '
		'--enable-libxavs2 '
		
		# HW Dec/Enc
		'--enable-libmfx '
		'--enable-amf '
		'--enable-ffnvcodec '
		'--enable-cuvid '
		#'--enable-cuda-sdk ' --enable-nonfree
		'--enable-opengl '
		'--enable-d3d11va '
		'--enable-nvenc '
		'--enable-nvdec '
		'--enable-dxva2 '
		
		'--enable-gpl '
		
		'--extra-version=DeadSix27/python_cross_compile_script '
		#'--enable-avresample ' # deprecated.
		'--pkg-config-flags="--static" '
		#'--extra-libs="-liconv" ' # -lschannel #-lsecurity -lz -lcrypt32 -lintl -liconv -lpng -loleaut32 -lstdc++ -lspeexdsp -lpsapi
		'--extra-cflags="-DLIBTWOLAME_STATIC" '
		'--extra-cflags="-DMODPLUG_STATIC" '
	,
}
PRODUCTS = {
	'aom' : {
		'repo_type' : 'git',
		'url' : 'https://aomedia.googlesource.com/aom',
		'branch' : '9284af62c37d62117c007d100e0442f144220ab8', #'f8b03215b8924c610d98142d8e4258ee1da1364c',
		'conf_system' : 'cmake',
		'source_subfolder' : 'build',
		'configure_options': '.. {cmake_prefix_options} ' 
			'-DCMAKE_INSTALL_PREFIX={product_prefix}/aom.installed '
			'-DCONFIG_LOWBITDEPTH=0 -DCONFIG_HIGHBITDEPTH=1 '
			'-DCONFIG_AV1=1 -DHAVE_PTHREAD=1 -DBUILD_SHARED_LIBS=0 -DENABLE_DOCS=0 -DCONFIG_INSTALL_DOCS=0 '
			'-DCONFIG_INSTALL_BINS=1 -DCONFIG_INSTALL_LIBS=0 '
			'-DCONFIG_INSTALL_SRCS=0 -DCONFIG_UNIT_TESTS=0 -DENABLE_TESTS=0 -DENABLE_TESTDATA=0 '
			'-DCONFIG_AV1_DECODER=1 -DCONFIG_AV1_ENCODER=1 '
			'-DCONFIG_MULTITHREAD=1 -DCONFIG_PIC=1 -DCONFIG_COEFFICIENT_RANGE_CHECKING=0 '
			'-DCONFIG_RUNTIME_CPU_DETECT=1 -DCONFIG_WEBM_IO=1 '
			'-DCONFIG_SPATIAL_RESAMPLING=1 -DENABLE_NASM=off'
		,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'aom-av1' },
	},
	'dav1d' : {
		'repo_type' : 'git',
		'url' : 'https://code.videolan.org/videolan/dav1d.git',
		'conf_system' : 'meson',
		'build_system' : 'ninja',
		'source_subfolder' : 'build',
		'configure_options': ''
			'--prefix={product_prefix}/dav1d.installed  '
			'--libdir={product_prefix}/dav1d.installed/lib '
			'--default-library=static '
			'--buildtype=plain '
			'--backend=ninja '
			'--buildtype=release '
			'--cross-file={meson_env_file} ./ ..'
      ,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'dav1d' },
	},
	'vpx' : {
		'repo_type' : 'git',
		'url' : 'https://chromium.googlesource.com/webm/libvpx',
		'rename_folder' : 'vpx_git',
		'configure_options':
			'--target={bit_name2}-{bit_name_win}-gcc '
			'--prefix={product_prefix}/vpx_git.installed '
			'--disable-shared --enable-static --enable-webm-io --enable-vp9 '
			'--enable-vp8 --enable-runtime-cpu-detect '
			'--enable-vp9-highbitdepth --enable-vp9-postproc --enable-coefficient-range-checking '
			'--enable-error-concealment --enable-better-hw-compatibility '
			'--enable-multi-res-encoding --enable-vp9-temporal-denoising '
			'--enable-tools --disable-docs --enable-examples --disable-install-docs --disable-unit-tests --disable-decode-perf-tests --disable-encode-perf-tests --disable-avx512 --as=nasm' #--as=yasm'
		,
		'env_exports' : {
			'CROSS' : '{cross_prefix_bare}',
		},
		'custom_cflag' : '-fno-asynchronous-unwind-tables',
		'patches': (
			( 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/vpx_160_semaphore.patch', '-p1' ),
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'vpx' },
	},
	'scxvid' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/DeadSix27/SCXvid-standalone',
		'conf_system' : 'cmake',
		'source_subfolder' : 'build',
		'configure_options': '.. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={product_prefix}/SCXvid-standalone_git.installed',
		'run_post_install': [
			'{cross_prefix_bare}strip -v {product_prefix}/SCXvid-standalone_git.installed/bin/scxvid.exe',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'SCXvid-standalone' },
	},
	'x264' : {
		'repo_type' : 'git',
		'url' : 'https://git.videolan.org/git/x264.git',
		'configure_options': '--host={target_host} --enable-static --cross-prefix={cross_prefix_bare} --prefix={product_prefix}/x264_git.installed --enable-strip --bit-depth=all',
		'env_exports' : {
			'PKGCONFIG' : 'pkg-config',
		},
		'depends_on' : [
			'libffmpeg',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'x264' },
	},
	'cuetools' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/svend/cuetools.git',
		'configure_options': '--host={target_host} --prefix={product_prefix}/cuetools_git.installed --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'cuetools' },
	},
	'curl' : {
		'repo_type' : 'git',
		# 'debug_confighelp_and_exit' : True,
		'url' : 'https://github.com/curl/curl',
		'rename_folder' : 'curl_git',
		'env_exports' : {
			'LIBS' : '-lcrypt32',
			'libsuff' : '/',
		},
		# 'patches' : [
			# ['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/curl/0001-fix-build-with-libressl.patch', '-p1' ],
		# ],
		'run_post_patch' : [
			'sed -i.bak \'s/SSL_LDFLAGS="-L$LIB_OPENSSL"/SSL_LDFLAGS=""/\' configure.ac',
			'autoreconf -fiv',
		],
		'configure_options': '--enable-static --disable-shared --target={bit_name2}-{bit_name_win}-gcc --host={target_host} --build=x86_64-linux-gnu --with-libssh2 --with-ca-fallback --without-winssl --prefix={product_prefix}/curl_git.installed --exec-prefix={product_prefix}/curl_git.installed',
		'depends_on': (
			'zlib', 'libssh2',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'cURL' },
	},
	'wget' : {
		'repo_type' : 'git',
		'url' : 'https://git.savannah.gnu.org/git/wget.git',
		# 'branch' : 'tags/v1.19.1',
		'rename_folder' : 'wget_git',
		'recursive_git' : True,
		'configure_options': '--target={bit_name2}-{bit_name_win}-gcc --host={target_host} --build=x86_64-linux-gnu --with-ssl=openssl --enable-nls --enable-dependency-tracking --with-metalink --prefix={product_prefix}/wget_git.installed --exec-prefix={product_prefix}/wget_git.installed',
		'cflag_addition' : ' -DIN6_ARE_ADDR_EQUAL=IN6_ADDR_EQUAL', #-DGNUTLS_INTERNAL_BUILD
		'patches' : [
			[ 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/wget/0001-remove-RAND_screen-which-doesn-t-exist-on-mingw.patch', '-p1' ],
			[ 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/wget/0001-wget-look-for-ca-bundle.trust.crt-in-exe-path-by-def.patch', '-p1' ],
			[ 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/wget/wget.timegm.patch', '-p1' ],
		],
		'run_post_build': [
			'if [ -f "/etc/ssl/certs/ca-certificates.crt" ] ; then cp -v /etc/ssl/certs/ca-certificates.crt "{product_prefix}/wget_git.installed/bin/ca-bundle.trust.crt" ; fi',
		],
		'depends_on': [
			'zlib', 'libressl', 'libpsl',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'wget' },
	},
	'ffmpeg_static' : {
		'repo_type' : 'git',
		'url' : 'git://git.ffmpeg.org/ffmpeg.git',
		'rename_folder' : 'ffmpeg_static_git',
		'configure_options': '!VAR(ffmpeg_base_config)VAR! --enable-libbluray --prefix={product_prefix}/ffmpeg_static_git.installed --disable-shared --enable-static',
		'depends_on': [ 'ffmpeg_depends' ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ffmpeg (static)' },
	},
	'ffmpeg_static_opencl' : {
		'repo_type' : 'git',
		'url' : 'git://git.ffmpeg.org/ffmpeg.git',
		'rename_folder' : 'ffmpeg_static_opencl_git',
		'configure_options': '!VAR(ffmpeg_base_config)VAR! --enable-libbluray --prefix={product_prefix}/ffmpeg_static_opencl_git.installed --disable-shared --enable-static --enable-opencl',
		'depends_on': [ 'ffmpeg_depends', 'opencl_icd' ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ffmpeg (static (OpenCL))' },
	},
	'ffmpeg_static_non_free' : { # with decklink, fdk-aac
		'repo_type' : 'git',
		'url' : 'git://git.ffmpeg.org/ffmpeg.git',
		'rename_folder' : 'ffmpeg_static_non_free',
		'configure_options': '!VAR(ffmpeg_base_config)VAR! --enable-libbluray --prefix={product_prefix}/ffmpeg_static_non_free.installed --disable-shared --enable-static --enable-nonfree --enable-libfdk-aac --enable-decklink',
		'depends_on': [ 'ffmpeg_depends', 'decklink_headers', 'fdk_aac' ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ffmpeg NonFree (static)' },
	},
	'ffmpeg_static_non_free_opencl' : { # with decklink, fdk-aac and opencl
		'repo_type' : 'git',
		'url' : 'git://git.ffmpeg.org/ffmpeg.git',
		'rename_folder' : 'ffmpeg_static_non_free_opencl',
		'configure_options': '!VAR(ffmpeg_base_config)VAR! --enable-libbluray --prefix={product_prefix}/ffmpeg_static_non_free_opencl.installed --disable-shared --enable-static --enable-opencl --enable-nonfree --enable-libfdk-aac --enable-decklink',
		'depends_on': [ 'ffmpeg_depends', 'decklink_headers', 'fdk_aac', 'opencl_icd' ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ffmpeg NonFree (static (OpenCL))' },
	},
	'ffmpeg_shared' : {
		'repo_type' : 'git',
		'url' : 'git://git.ffmpeg.org/ffmpeg.git',
		'rename_folder' : 'ffmpeg_shared_git',
		'configure_options': '!VAR(ffmpeg_base_config)VAR! --prefix={product_prefix}/ffmpeg_shared_git.installed --enable-shared --disable-static --disable-libbluray --disable-libgme',
		'depends_on': [ 'ffmpeg_depends' ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ffmpeg (shared)' },
	},
	'x265_multibit' : {
		'repo_type' : 'mercurial',
		'url' : 'https://bitbucket.org/multicoreware/x265',
		'rename_folder' : 'x265_multibit_hg',
		'source_subfolder': 'source',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_AR={cross_prefix_full}ar -DENABLE_SHARED=OFF -DENABLE_ASSEMBLY=ON -DEXTRA_LIB="x265_main10.a;x265_main12.a" -DEXTRA_LINK_FLAGS="-L{offtree_prefix}/libx265_10bit/lib;-L{offtree_prefix}/libx265_12bit/lib" -DLINKED_10BIT=ON -DLINKED_12BIT=ON -DCMAKE_INSTALL_PREFIX={product_prefix}/x265_multibit_hg.installed',
		'conf_system' : 'cmake',
		'_info' : { 'version' : 'mercurial (default)', 'fancy_name' : 'x265 (multibit 12/10/8)' },
		'depends_on' : [ 'libx265_multibit_10', 'libx265_multibit_12' ],
	},
	'flac' : {
		'repo_type' : 'git',
		'url' : 'https://git.xiph.org/flac.git',
		'configure_options': '--host={target_host} --prefix={product_prefix}/flac_git.installed --disable-shared --enable-static',
		'depends_on': [
			'libogg',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'FLAC' },
		'packages': {
			'ubuntu' : [ 'docbook-to-man' ],
		},
	},
	'lame' : {
		# 'debug_downloadonly': True,
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/lame/files/lame/
			{ "url" : "https://sourceforge.net/projects/lame/files/lame/3.100/lame-3.100.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e" }, ], },
			{ "url" : "https://fossies.org/linux/misc/lame-3.100.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e" }, ], },
		],
		'patches' : (
			('https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-lame/0007-revert-posix-code.patch','-p1'), # borrowing their file since lame will fix this shortly anyway, its already fixed on svn
		),
		'depends_on' : ['iconv'],
		'configure_options': '--host={target_host} --without-libiconv-prefix --prefix={product_prefix}/lame-3.100.installed --disable-shared --enable-static --enable-nasm',
		'_info' : { 'version' : '3.10', 'fancy_name' : 'LAME3' },
	},
	'vorbis-tools' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/xiph/vorbis-tools.git',
		'configure_options': '--host={target_host} --prefix={product_prefix}/vorbis-tools_git.installed --disable-shared --enable-static --without-libintl-prefix',
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/vorbis_tools_odd_locale.patch','-p1'),
		),
		'depends_on': [
			'libvorbis',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'vorbis-tools' },
	},
	'sox' : {
		'repo_type' : 'git',
		'rename_folder' : 'sox_git',
		'url' : 'git://git.code.sf.net/p/sox/code',
		'configure_options': '--host={target_host} --prefix={product_prefix}/sox_git.installed --disable-shared --enable-static --without-gsm',
		'run_post_patch' : (
			'autoreconf -fiv',
			'if [ -f "{target_prefix}/lib/libgsm.a" ] ; then mv {target_prefix}/lib/libgsm.a {target_prefix}/lib/libgsm.a.disabled ; fi',
			'if [ -d "{target_prefix}/include/gsm" ] ; then mv {target_prefix}/include/gsm {target_prefix}/include/gsm.disabled ; fi',
		),
		'run_post_install' : (
			'if [ -f "{target_prefix}/lib/libgsm.a.disabled" ] ; then mv {target_prefix}/lib/libgsm.a.disabled {target_prefix}/lib/libgsm.a ; fi',
			'if [ -d "{target_prefix}/include/gsm.disabled" ] ; then mv {target_prefix}/include/gsm.disabled {target_prefix}/include/gsm ; fi',
		),
		'depends_on': [
			'libvorbis','gettext',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'SoX' },
	},
	'w2x' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/DeadSix27/waifu2x-converter-cpp',
		'needs_make_install':False,
		'conf_system' : 'cmake',
		'source_subfolder' : 'out',
		# 'depends_on': [ 'opencl_icd' ],
		'configure_options': '.. {cmake_prefix_options} -DFORCE_AMD=ON -DCMAKE_INSTALL_PREFIX={product_prefix}/w2x.installed',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'waifu2x-converter-cpp' },
	},
	'mp4box' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/gpac/gpac.git',
		'rename_folder' : 'mp4box_git',
		'do_not_bootstrap' : True,
		'run_post_patch' : [
			'sed -i.bak \'s/has_dvb4linux="yes"/has_dvb4linux="no"/g\' configure',
			'sed -i.bak \'s/targetos=`uname -s`/targetos=MINGW64/g\' configure',
			'sed -i.bak \'s/extralibs="-lm"/extralibs=""/g\' configure',
			'sed -i.bak \'s/SHFLAGS=-shared/SHFLAGS=/g\' configure',
			'sed -i.bak \'s/extralibs="$extralibs -lws2_32 -lwinmm -limagehlp"/extralibs="$extralibs -lws2_32 -lwinmm -lz"/g\' configure',
		],
		'configure_options': '--host={target_host} --target-os={bit_name3} --prefix={product_prefix}/mp4box_git.installed --static-modules --cross-prefix={cross_prefix_bare} --static-mp4box --enable-static-bin --disable-oss-audio --disable-x11 --disable-docs --sdl-cfg={cross_prefix_full}sdl2-config --disable-shared --enable-static',
		'depends_on': [
			 'sdl2', 'libffmpeg',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'mp4box' },
	},
	'mpv' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/mpv-player/mpv.git',
		'build_system' : 'waf',
		'conf_system' : 'waf',
		'env_exports' : {
			'DEST_OS' : 'win32',
			'TARGET'  : '{target_host}',
			# 'LDFLAGS' : '-ld3d11 -llzma',
		},
		'run_post_patch' : [
			'cp -nv "/usr/bin/pkg-config" "{cross_prefix_full}pkg-config"',
			'sed -i.bak "s/encoder_encode/mpv_encoder_encode/" common/encode_lavc.h', # Dirty work-around for xavs2, no idea how else to fix this.
			'sed -i.bak "s/encoder_encode/mpv_encoder_encode/" video/out/vo_lavc.c',  #
			'sed -i.bak "s/encoder_encode/mpv_encoder_encode/" audio/out/ao_lavc.c',  #
			'sed -i.bak "s/encoder_encode/mpv_encoder_encode/" common/encode_lavc.c', #
		],
		'configure_options':
			'--enable-libmpv-shared '
			'--disable-debug-build '
			'--prefix={product_prefix}/mpv_git.installed '
			'--enable-sdl2 '
			'--enable-rubberband '
			'--enable-lcms2 '
			'--enable-dvdread '
			'--enable-openal '
			'--enable-dvdnav '
			'--enable-libbluray '
			'--enable-cdda '
			#'--enable-egl-angle-lib ' # not maintained anymore apparently, crashes for me anyway.
			'--enable-libass '
			'--enable-lua '
			'--enable-vapoursynth '
			'--enable-uchardet '
			'--disable-xv '
			'--disable-pulse '
			'--disable-alsa '
			'--disable-jack '
			'--disable-x11 '
			'--disable-wayland '
			'--disable-wayland-protocols '
			'--disable-wayland-scanner '
			'--enable-libarchive '
			'--enable-javascript '
			'--disable-manpage-build '
			'--enable-pdf-build '
			'TARGET={target_host} '
			'DEST_OS=win32 '
		,
		'depends_on' : [
			'libffmpeg', 'python3_libs', 'vapoursynth_libs','sdl2', 'luajit', 'lcms2', 'libdvdnav', 'libbluray', 'openal', 'libass', 'libcdio-paranoia', 'libjpeg-turbo', 'uchardet', 'libarchive', 'mujs', 'shaderc', 'vulkan_loader',
		],
		'packages': {
			'arch' : [ 'rst2pdf' ],
		},
		'patches' : [
			# Enable PR's by preference
			[ 'https://github.com/mpv-player/mpv/pull/5411.patch', '-p1' ], # osc: seekranges enhancement
			[ 'https://github.com/mpv-player/mpv/pull/6292.patch', '-p1' ], # some left-shift to mmouse alias PR
			# [ 'https://github.com/mpv-player/mpv/pull/6158.patch', '-p1' ], # wm4's controversial giant pr
			# [ 'https://github.com/mpv-player/mpv/pull/6326.patch', '-p1' ], # hwdec_cuda: Use explicit synchronisation in vulkan interop	
		],
		'run_post_configure': (
			'sed -i.bak -r "s/(--prefix=)([^ ]+)//g;s/--color=yes//g" build/config.h',
		),
		'run_post_install': (
			'{cross_prefix_bare}strip -v {product_prefix}/mpv_git.installed/bin/mpv.com',
			'{cross_prefix_bare}strip -v {product_prefix}/mpv_git.installed/bin/mpv.exe',
			'{cross_prefix_bare}strip -v {product_prefix}/mpv_git.installed/bin/mpv-1.dll',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'mpv' },
	},
	'youtube-dl' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/rg3/youtube-dl.git',
		'install_options' : 'youtube-dl PREFIX="{product_prefix}/youtube-dl_git.installed"',
		'run_post_patch' : [
			'sed -i.bak \'s/pandoc.*/touch youtube-dl.1/g\' Makefile', # "disables" doc, the pandoc requirement is so annoyingly big..
		],
		'run_post_install' : [
			'if [ -f "{product_prefix}/youtube-dl_git.installed/bin/youtube-dl" ] ; then mv "{product_prefix}/youtube-dl_git.installed/bin/youtube-dl" "{product_prefix}/youtube-dl_git.installed/bin/youtube-dl.py" ; fi',
		],
		'build_options': 'youtube-dl',
		'patches' : [
			( 'https://github.com/DeadSix27/youtube-dl/commit/4a386648cf85511d9eb283ba488858b6a5dc2444.patch', '-p1' ),
		],
		'needs_configure' : False,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'youtube-dl' },
	},
	# ###############################################################################################################
	# ###############################################################################################################
	# ## Most of these packages I haven't used/updated in a long while, most if not all probably stopped building. ##
	# ###############################################################################################################
	# ###############################################################################################################
	#'mkvtoolnix': {
	#	'repo_type' : 'git',
	#	'recursive_git' : True,
	#	'build_system' : 'rake',
	#	'url' : 'https://gitlab.com/mbunkus/mkvtoolnix.git', #why gitlab? At least its not sourceforge...
	#	'configure_options':
	#		'--host={target_host} --prefix={product_prefix}/mkvtoolnix_git.installed --disable-shared --enable-static'
	#		' --with-boost={target_prefix} --with-boost-system=boost_system --with-boost-filesystem=boost_filesystem --with-boost-date-time=boost_date_time --with-boost-regex=boost_regex --enable-optimization --enable-qt --enable-static-qt'
	#		' --with-moc={mingw_binpath2}/moc --with-uic={mingw_binpath2}/uic --with-rcc={mingw_binpath2}/rcc --with-qmake={mingw_binpath2}/qmake'
	#		#' QT_LIBS="-lws2_32 -lprcre"'
	#	,
	#	'build_options': '-v',
	#	'depends_on' : [
	#		'cmark','libfile','libflac','boost','qt5','gettext'
	#	],
	#	'packages': {
	#		'ubuntu' : [ 'xsltproc', 'docbook-utils', 'rake', 'docbook-xsl' ],
	#	},
	#	'run_post_install': (
	#		'{cross_prefix_bare}strip -v {product_prefix}/mkvtoolnix_git.installed/bin/mkvmerge.exe',
	#		'{cross_prefix_bare}strip -v {product_prefix}/mkvtoolnix_git.installed/bin/mkvtoolnix-gui.exe',
	#		'{cross_prefix_bare}strip -v {product_prefix}/mkvtoolnix_git.installed/bin/mkvextract.exe',
	#		'{cross_prefix_bare}strip -v {product_prefix}/mkvtoolnix_git.installed/bin/mkvinfo-gui.exe',
	#		'{cross_prefix_bare}strip -v {product_prefix}/mkvtoolnix_git.installed/bin/mkvpropedit.exe',
	#		'{cross_prefix_bare}strip -v {product_prefix}/mkvtoolnix_git.installed/bin/mkvinfo.exe',
	#	),
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'mkvtoolnix' },
    #
	#},
	#'gdb' : {
	#	'repo_type' : 'git',
	#	'url' : 'git://sourceware.org/git/binutils-gdb.git',
	#	'configure_options': '--host={target_host} --enable-static --enable-lto --prefix={product_prefix}/gdb_git.installed',
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'GDB' },
	#},
	# 'mediainfo' : { #unused
	# 	'repo_type' : 'git',
	# 	'branch' : 'v0.7.94',
	# 	'custom_cflag' : '',
	# 	'recursive_git' : True,
	# 	'url' : 'https://github.com/MediaArea/MediaInfo.git',
	# 	'source_subfolder' : 'Project/GNU/CLI',
	# 	'rename_folder' : 'mediainfo_git',
	# 	'configure_options': '--host={target_host} --prefix={product_prefix}/mediainfo_git.installed --disable-shared --disable-static-libs',
	# 	'depends_on': [
	# 		'libmediainfo',
	# 	],
	# 	'run_post_configure' : [
	# 		'sed -i.bak \'s/ -DSIZE_T_IS_LONG//g\' Makefile',
	# 	],
	# 	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'MediaInfo' },
	# 	'_disabled' : True,
	# },
	# 'patch' : { # unused
	# 	'repo_type' : 'archive',
	# 	'download_locations' : [
	# 		{ "url" : "https://ftp.gnu.org/gnu/patch/patch-2.7.6.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "ac610bda97abe0d9f6b7c963255a11dcb196c25e337c61f94e4778d632f1d8fd" }, ], },
	# 		{ "url" : "https://fossies.org/linux/misc/patch-2.7.6.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "ac610bda97abe0d9f6b7c963255a11dcb196c25e337c61f94e4778d632f1d8fd" }, ], },
	# 	],
	# 	'configure_options': '--host={target_host} --prefix={product_prefix}/patch.installed --disable-shared --enable-static',
	# 	'_info' : { 'version' : '2.7.6', 'fancy_name' : 'patch' },
	# },
	# 'aria2' : { # broken
	# 	'repo_type' : 'git',
	# 	'url' : 'https://github.com/aria2/aria2.git',
	# 	'env_exports' : {
	# 		#'LDFLAGS' : '-static',
	# 		#'LIBS' : '-static-libgcc -static-libstdc++ -lz -lole32',
	# 	},
	# 	'configure_options':
	# 		' --host={target_host} --prefix={product_prefix}/aria2_git.installed'
	# 		' --disable-shared --enable-static'
	# 		' --without-included-gettext --disable-nls --without-gnutls --disable-silent-rules --with-openssl=yes --without-wintls --without-libxml2'
	# 		' ARIA2_STATIC=yes'
	# 	,
	# 	'configure_optionsb':
	# 		' --host={target_host} --prefix={product_prefix}/aria2_git.installed'
	# 		' --without-included-gettext --disable-nls --disable-shared --enable-static --with-ca-bundle=ca-bundle.trust.crt'
	# 		' --with-openssl --with-libexpat --with-libz --with-libgmp --without-wintls'
	# 		' --with-sqlite3 --with-libxml2 --without-gnutls --disable-silent-rules'
	# 		' --with-cppunit-prefix={target_prefix} ARIA2_STATIC=yes'
	# 	,
	# 	'run_post_patch' : [
	# 		'autoreconf -fiv'
	# 	],
	# 	'run_post_install': [
	# 		'{cross_prefix_bare}strip -v {product_prefix}/aria2_git.installed/bin/aria2c.exe',
	# 	],
	# 	'depends_on': [
	# 		'zlib', 'libressl',
	# 	],
	# 	# 'depends_on': [
	# 		# 'zlib', 'libxml2', 'expat', 'gmp', 'libsqlite3', 'libssh2', 'cppunit', 'libressl', #'gnutls', # 'c-ares', 'libsqlite3', 'openssl_1_1'
	# 	# ],
	# 	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'aria2' },
	# },
	# 'vlc' : { # not working
	# 	'repo_type' : 'git',
	# 	'url' : 'https://github.com/videolan/vlc.git', # https://git.videolan.org/git/vlc.git is slow..
	# 	'configure_options':
	# 		'--host={target_host} --prefix={product_prefix}/vlc_git.installed --disable-lua --enable-qt --disable-ncurses --disable-dbus --disable-sdl --disable-telx --enable-nls LIBS="-lbcrypt -lbz2"'
	# 	,
	# 	'depends_on' : [
	# 		'lua', 'a52dec',
	# 	],
	# 	# 'patches' : [
	# 		# ('https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-vlc-git/0002-MinGW-w64-lfind-s-_NumOfElements-is-an-unsigned-int.patch','-p1'),
	# 		# ('https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-vlc-git/0003-MinGW-w64-don-t-pass-static-to-pkg-config-if-SYS-min.patch','-p1'),
	# 		# ('https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-vlc-git/0004-Revert-Win32-prefer-the-static-libraries-when-creati.patch','-p1'),
	# 	# ],
	# 	'env_exports' : {
	# 		'LIBS' : '-lbcrypt -lbz2', # add the missing bcrypt Link, is windows SSL api, could use gcrypt or w/e idk what that lib is, i'd probably rather use openssl_1_1
	# 	},
	# 	# 'download_header' : [
	# 	# 	'https://raw.githubusercontent.com/gongminmin/UniversalDXSDK/master/Include/dxgi1_3.h',
	# 	# 	'https://raw.githubusercontent.com/gongminmin/UniversalDXSDK/master/Include/dxgi1_4.h',
	# 	# 	'https://raw.githubusercontent.com/gongminmin/UniversalDXSDK/master/Include/dxgi1_5.h',
	# 	# 	'https://raw.githubusercontent.com/gongminmin/UniversalDXSDK/master/Include/dxgi1_6.h',
	# 	# ],
	# 	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'VLC (git)' },
	# 	'_disabled' : True,
	# },
	# 'mpd' : { # broken
	# 	'repo_type' : 'git',
	# 	'url' : 'https://github.com/MaxKellermann/MPD.git',
	# 	'configure_options' : '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-wavpack --disable-gme --disable-bzip2 --disable-cdio-paranoia --disable-sqlite --enable-silent-rules --disable-icu LDFLAGS="-static" LIBS="-static-libgcc -static-libstdc++ -lz -lole32"',
	# 	'env_exports' : {
	# 		'LDFLAGS' : '-static',
	# 		'LIBS' : '-static-libgcc -static-libstdc++ -lz -lole32',
	# 		'CXXFLAGS' : '-O2 -g',
	# 	},
	# 	'_disabled' : True,
	# },
	#'clementine' : { # requires qt4....... so no. we'll keep it for future reference.
	#	'repo_type' : 'git',
	#	'url' : 'https://github.com/clementine-player/Clementine.git',
	#	'needs_make_install':False,
	#	'conf_system' : 'cmake',
	#	'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF',
	#	'depends_on': [
	#		'qt4',
	#	],
	#	'_disabled': True,
	#},
	#'amarok' : { # requires qt4....... so no. we'll keep it for future reference.
	#	'repo_type' : 'git',
	#	'url' : 'git://anongit.kde.org/amarok.git',
	#	'needs_make_install':False,
	#	'conf_system' : 'cmake',
	#	'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix}',
	#	# 'custom_cflag' : '-DTAGLIB_STATIC',
	#	'env_exports' : {
	#		'CPPDEFINES' : '-DTAGLIB_STATIC',
	#		# build.env.Append(CPPDEFINES = 'TAGLIB_STATIC')
	#	},
	#	'depends_on': [
	#		'taglib',
	#	],
	#},
	# 'filezilla' : { # I haven't touched this in a while, probably stopped building.
	# 	'repo_type' : 'svn',
	# 	'folder_name' : 'filezilla_svn',
	# 	'url' : 'https://svn.filezilla-project.org/svn/FileZilla3/trunk',
	# 	'configure_options': '--host={target_host} --prefix={product_prefix}/filezilla_svn.installed --disable-shared --enable-static --disable-manualupdatecheck --disable-autoupdatecheck --with-pugixml=builtin host_os=mingw',
	# 	'run_post_patch' : [
	# 		'autoreconf -fiv',
	# 		'sed -i.bak \'s/extern _SYM_EXPORT gnutls_free/extern gnutls_free/\' "{target_prefix}/include/gnutls/gnutls.h"', #edit gnutls.h and remove the _SYM_EXPORT part apparently...? : https://forum.filezilla-project.org/viewtopic.php?t=1227&start=180
	# 	],
	# 	'depends_on' : [
	# 		'libfilezilla',
	# 		'gnutls',
	# 		'wxwidgets',
	# 		'libsqlite3'
	# 	 ],
	# 	'env_exports' : {
	# 		'LIBGNUTLS_LIBS' : '"-L{target_prefix}/lib -lgnutls -lnettle -lhogweed -lgmp -lcrypt32 -lws2_32 -lz"',
	# 		'LIBS' : '-lgnutls',
	# 		'CXXFLAGS' : '-Wall -O2',
	# 	},
	# 	'patches' : [
	# 		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/filezilla/0001-remove-32bit-fzshellext.patch','-p1'),
	# 	],
	# 	'run_post_install' : [
	# 		'mv "{target_prefix}/include/gnutls/gnutls.h.bak" "{target_prefix}/include/gnutls/gnutls.h"'
	# 	],
	# 	'packages': {
	# 		'ubuntu' : [ 'wxrc' ],
	# 	},
	# 	'_info' : { 'version' : 'svn (master)', 'fancy_name' : 'FileZilla (64Bit only)' },
    # 
	# },
	# 'mpv_gui_qt5' : {
	# 	'repo_type' : 'git',
	# 	'url' : 'https://github.com/DeadSix27/Baka-MPlayer',
	# 	'rename_folder' : 'mpv_gui_qt5_git',
	# 	'configure_options' :
	# 		'CONFIG+=embed_translations lupdate="{target_sub_prefix}/bin/lupdate" lrelease="{target_sub_prefix}/bin/lrelease" PKG_CONFIG={cross_prefix_full}pkg-config INSTALL_ROOT={product_prefix}/mpv_gui_qt5_git.installed'
	# 		' LIBS+=-L{target_sub_prefix}/lib INCLUDEPATH+=-I{target_sub_prefix}/include'
	# 	,
	# 	'run_post_patch' : [
	# 		'cp -nv "/usr/bin/pkg-config" "{cross_prefix_full}pkg-config"'
	# 	],
	# 	'install_options' : 'INSTALL_ROOT={product_prefix}/mpv_gui_qt5_git.installed',
	# 	'env_exports' : {
	# 		'QTROOT' : '{target_sub_prefix}/bin',
	# 		'QMAKE' : '{target_sub_prefix}/bin/qmake',
	# 		'PKG_CONFIG' : '{cross_prefix_full}pkg-config'
	# 	},
	# 	'depends_on' : [
	# 		'qt5',
	# 		'libmpv',
	# 		'libzip'
	# 	],
	# },
	# 'mediainfo_dll' : { # wont produce dll
	# 	# 'debug_downloadonly': True,
	# 	'repo_type' : 'git',
	# 	# 'branch' : 'v0.7.94',
	# 	'source_subfolder' : 'Project/GNU/Library',
	# 	'rename_folder' : 'mediainfo_dll',
	# 	'url' : 'https://github.com/MediaArea/MediaInfoLib.git',
	# 	'configure_options' : '--host={target_host} --target={bit_name2}-{bit_name_win}-gcc --prefix={product_prefix}/mediainfo_dll.installed --enable-static --disable-shared', # --enable-static --disable-shared --enable-shared=no
	# 	'run_post_patch' : [
	# 		'sed -i.bak \'s/Windows.h/windows.h/\' ../../../Source/MediaInfo/Reader/Reader_File.h',
	# 		'sed -i.bak \'s/Windows.h/windows.h/\' ../../../Source/MediaInfo/Reader/Reader_File.cpp',
	# 	],
	# 	'run_post_configure' : [
	# 		'sed -i.bak \'s/ -DSIZE_T_IS_LONG//g\' Makefile',
	# 	],
	# 	'build_options': '{make_prefix_options}',
	# 	'depends_on': [
	# 		'zenlib', 'libcurl',
	# 	],
	# 	# 'patches' : [
	# 		# ('libmediainfo-1-fixes.patch','-p1', '../../..'),
	# 	# ],
	# 	'env_exports' : { 'PKG_CONFIG' : 'pkg-config' },
	# 	#'_info' : { 'version' : 'git (master)', 'fancy_name' : 'MediaInfoDLL' },
	# },
}
DEPENDS = {
	'crossc' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/rossy/crossc.git',
		'cpu_count' : '1',
		'recursive_git' : True,
		'needs_configure' : False,
		'build_options': '{make_prefix_options} static',
		'install_options' : '{make_prefix_options} prefix={target_prefix} install-static',
		'run_post_patch' : [
			'git submodule update --remote --recursive',
			'rm -vf {target_prefix}/lib/pkgconfig/crossc.pc',
		],
		'run_post_install' : [
			"rm -vf {target_prefix}/lib/libcrossc.dll.a", # we only want static, somehow this still gets installed tho.
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'crossc' },
	},
	'shaderc' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/google/shaderc.git',
		'configure_options': 'cmake .. {cmake_prefix_options} -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE=cmake/linux-mingw-toolchain.cmake -DCMAKE_INSTALL_PREFIX={target_prefix} -DSHADERC_SKIP_INSTALL=ON -DSHADERC_SKIP_TESTS=ON -DMINGW_COMPILER_PREFIX={cross_prefix_bare}', #-DCMAKE_CXX_FLAGS="${{CMAKE_CXX_FLAGS}} -fno-rtti"
		'source_subfolder' : '_build', #-B. -H..
		'conf_system' : 'cmake',
		# 'cpu_count' : '1', #...
		'needs_make_install' : False,
		'build_options': '',
		# 'patches' : [
			# ['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/shaderc/shaderc-0001-add-script-for-cloning-dependencies.patch', '-p1', '..'],
		# ],
		'run_post_patch' : [
			# 'mkdir _build',
			# 'chmod u+x pull.sh',
			# './pull.sh',
			'!SWITCHDIR|../third_party',
			'ln -sf {inTreePrefix}/glslang/ glslang',
			'ln -sf {inTreePrefix}/spirv-headers/ spirv-headers',
			'ln -sf {inTreePrefix}/spirv-tools/ spirv-tools',
			'!SWITCHDIR|../_build',
			"sed -i 's/add_subdirectory(examples)/#add_subdirectory(examples)/g' ../CMakeLists.txt",
			'mkdir -p third_party',
			'!SWITCHDIR|third_party',
			'ln -sf {inTreePrefix}/glslang glslang',
			'ln -sf {inTreePrefix}/spirv-headers spirv-headers',
			'ln -sf {inTreePrefix}/spirv-tools spirv-tools',
			'!SWITCHDIR|..',
		],
		'run_post_build' : (
			'cp -rv "../libshaderc/include/shaderc" "{target_prefix}/include/"',
			'cp -rv "libshaderc/libshaderc_combined.a" "{target_prefix}/lib/libshaderc_combined.a"',
			# 'cp -rv "libshaderc/libshaderc_combined.a" "{target_prefix}/lib/libshaderc_shared.a"',
		),
		'depends_on' : ['glslang', 'spirv_headers', 'spirv_tools', 'crossc'],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'shaderc' },
	},
	'glslang' : {
		'repo_type' : 'git',
		'rename_folder' : 'glslang',
		'url' : 'https://github.com/KhronosGroup/glslang.git',
		'needs_make' : False,
		'needs_make_install' : False,
		'needs_configure' : False,
		'recursive_git' : True,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'glslang' },
	},
	'spirv_headers' : {
		'repo_type' : 'git',
		'rename_folder' : 'spirv-headers',
		'url' : 'https://github.com/KhronosGroup/SPIRV-Headers.git',
		'needs_make' : False,
		'needs_make_install' : False,
		'needs_configure' : False,
		'recursive_git' : True,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'SPIRV Headers' },
	},
	'spirv_tools' : {
		'repo_type' : 'git',
		'rename_folder' : 'spirv-tools',
		'url' : 'https://github.com/KhronosGroup/SPIRV-Tools.git',
		'needs_make' : False,
		'needs_make_install' : False,
		'needs_configure' : False,
		'recursive_git' : True,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'SPIRV Tools' },
	},
	'vulkan_headers' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/KhronosGroup/Vulkan-Headers.git',
		'recursive_git' : True,
		'configure_options': '. {cmake_prefix_options} -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX={target_prefix}',
		'conf_system' : 'cmake',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'Vulkan headers' },
	},
	'vulkan_loader' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/KhronosGroup/Vulkan-Loader.git',
		'recursive_git' : True, 
		'configure_options': '. {cmake_prefix_options} -DVULKAN_HEADERS_INSTALL_DIR={target_prefix} -DCMAKE_INSTALL_PREFIX={target_prefix} -DCMAKE_ASM-ATT_COMPILER={mingw_binpath}/{cross_prefix_bare}as -DBUILD_TESTS=OFF -DENABLE_STATIC_LOADER=ON -DCMAKE_C_FLAGS=\'-D_WIN32_WINNT=0x0600 -D__STDC_FORMAT_MACROS\' -DCMAKE_CXX_FLAGS=\'-D__USE_MINGW_ANSI_STDIO -D__STDC_FORMAT_MACROS -fpermissive -D_WIN32_WINNT=0x0600\'', #-D_WIN32_WINNT=0x0600 -D__STDC_FORMAT_MACROS" -D__USE_MINGW_ANSI_STDIO -D__STDC_FORMAT_MACROS -fpermissive -D_WIN32_WINNT=0x0600"
		'conf_system' : 'cmake',
		'patches' : [
			['https://raw.githubusercontent.com/DeadSix27/misc_patches/master/vulkan/0001-vulkan-loader-cross-compile-static-linking-hacks.patch','-p1'],
		],
		'run_post_install' : [
			'sed -i.bak \'s/Libs: -L${{libdir}} -lvulkan/Libs: -L${{libdir}} -lvulkan -lshlwapi -lcfgmgr32/\' "{target_prefix}/lib/pkgconfig/vulkan.pc"',
		],
		'depends_on' : [ 'vulkan_headers' ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'Vulkan Loader' },
	},
	'ffmpeg_depends' : { # this is fake dependency used to just inherit other dependencies, you could make other programs depend on this and have a smaller config for example.
		'is_dep_inheriter' : True,
		'depends_on' : [
			'zlib', 'bzip2', 'xz', 'libzimg', 'libsnappy', 'libpng', 'gmp', 'libnettle', 'gnutls', 'iconv', 'frei0r', 'libsndfile', 'libbs2b', 'wavpack',
			'libgme_game_music_emu', 'libwebp', 'flite', 'libgsm', 'sdl2', 'libopus', 'opencore-amr', 'vo-amrwbenc', 'libogg', 'libspeex', 'davs2', 'openmpt',
			'libvorbis', 'libtheora', 'freetype', 'expat', 'libxml2', 'libbluray', 'libxvid', 'xavs', 'xavs2', 'libsoxr', 'libx265_multibit', 'kvazaar', 'libaom',
			'libdav1d', 'vamp_plugin', 'fftw3', 'libsamplerate', 'librubberband', 'liblame' ,'twolame', 'vidstab', 'libmysofa', 'libcaca', 'libmodplug',
			'zvbi', 'libvpx', 'libilbc', 'libfribidi', 'gettext', 'libass', 'intel_quicksync_mfx', 'rtmpdump', 'libx264', 'libcdio', 'libcdio-paranoia', 'amf_headers', 'nv-codec-headers'
		],
	},
	'opencl_icd' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/KhronosGroup/OpenCL-ICD-Loader.git',
		'needs_make_install':False,
		'conf_system' : 'cmake',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF',
		'depends_on' : [ 'opencl_headers' ],
		'run_post_patch' : [
			'sed -i.bak \'s/Devpkey.h/devpkey.h/\' icd_windows_hkr.c',
		],
		'run_post_build' : [
			'if [ ! -f "already_ran_make_install" ] ; then cp -vf "libOpenCL.dll.a" "{target_prefix}/lib/libOpenCL.dll.a" ; fi',
			'if [ ! -f "already_ran_make_install" ] ; then touch already_ran_make_install ; fi',
		],
		'patches' : [
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/opencl/0001-OpenCL-git-prefix.patch','-p1'),
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/opencl/0002-OpenCL-git-header.patch','-p1'),
		],
	},
	'opencl_headers' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/KhronosGroup/OpenCL-Headers.git',
		'run_post_patch' : (
			'if [ ! -f "already_ran_make_install" ] ; then if [ ! -d "{target_prefix}/include/CL" ] ; then mkdir "{target_prefix}/include/CL" ; fi ; fi',
			'if [ ! -f "already_ran_make_install" ] ; then cp -v opencl22/CL/*.h "{target_prefix}/include/CL/" ; fi',
			'if [ ! -f "already_ran_make_install" ] ; then touch already_ran_make_install ; fi',
		),
		'needs_make':False,
		'needs_make_install':False,
		'needs_configure':False,
	},
	'cmark' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/commonmark/cmark.git',
		'conf_system' : 'cmake',
		'source_subfolder': '_build',
		'configure_options': '.. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DCMARK_STATIC=ON -DCMARK_SHARED=OFF -DCMARK_TESTS=OFF', #CMARK_STATIC_DEFINE
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'cmark' },
	},
	'libzip' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/nih-at/libzip.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'patches' : [
			# ('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libzip/0001-libzip-git-20170415-fix-static-build.patch','-p1'),
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libzip/0001-Fix-building-statically-on-mingw64.patch','-p1'),

		],
		'run_post_patch' : (
			'autoreconf -fiv',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libzip' },
	},
	'libmpv' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/mpv-player/mpv.git',
		'build_system' : 'waf',
		'conf_system' : 'waf',
		'rename_folder' : "libmpv_git",
		'env_exports' : {
			'DEST_OS' : 'win32',
			'TARGET'  : '{target_host}',
			'LDFLAGS' : '-ld3d11',
		},
		'run_post_patch' : (
			'cp -nv "/usr/bin/pkg-config" "{cross_prefix_full}pkg-config"',
			'sed -i.bak "s/encoder_encode/mpv_encoder_encode/" common/encode_lavc.h', # Dirty work-around for xavs2, no idea how else to fix this.
			'sed -i.bak "s/encoder_encode/mpv_encoder_encode/" video/out/vo_lavc.c',  #
			'sed -i.bak "s/encoder_encode/mpv_encoder_encode/" audio/out/ao_lavc.c',  #
			'sed -i.bak "s/encoder_encode/mpv_encoder_encode/" common/encode_lavc.c', #
		),
		'configure_options':
			'--enable-libmpv-shared '
			'--disable-debug-build '
			'--prefix={target_prefix} '
			'--enable-sdl2 '
			'--enable-rubberband '
			'--enable-lcms2 '
			'--enable-dvdread '
			'--enable-openal '
			'--enable-dvdnav '
			'--enable-libbluray '
			#'--enable-egl-angle-lib '
			'--disable-xv '
			'--disable-alsa '
			'--disable-pulse '
			'--disable-jack '
			'--disable-x11 '
			'--disable-wayland '
			'--disable-wayland-protocols '
			'--disable-wayland-scanner '
			'--enable-cdda '
			'--enable-libass '
			'--enable-lua '
			'--enable-vapoursynth '
			'--enable-encoding '
			'--enable-uchardet '
			'--enable-libarchive '
			'--enable-javascript '
			'--disable-manpage-build '
			'--enable-pdf-build '
			'TARGET={target_host} '
			'DEST_OS=win32 '
		,
		'depends_on' : [
			'libffmpeg', 'python3_libs', 'vapoursynth_libs','sdl2', 'luajit', 'lcms2', 'libdvdnav', 'libbluray', 'openal', 'libass', 'libcdio-paranoia', 'libjpeg-turbo', 'uchardet', 'libarchive', 'mujs', 'shaderc', 'vulkan_loader',
		],
		'packages': {
			'arch' : [ 'rst2pdf' ],
		},
		'run_post_configure': (
			'sed -i.bak -r "s/(--prefix=)([^ ]+)//g;s/--color=yes//g" build/config.h',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'mpv (library)' },
	},
	'boost' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/boost/files/boost/
			{ "url" : "https://sourceforge.net/projects/boost/files/boost/1.68.0/boost_1_68_0.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "7f6130bc3cf65f56a618888ce9d5ea704fa10b462be126ad053e80e553d6d8b7" }, ], },
			{ "url" : "https://fossies.org/linux/misc/boost_1_68_0.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "7f6130bc3cf65f56a618888ce9d5ea704fa10b462be126ad053e80e553d6d8b7" }, ], },
		],
		'needs_make':False,
		'needs_make_install':False,
		'needs_configure':False,
		'run_post_patch': (
			'if [ ! -f "already_configured_0" ] ; then ./bootstrap.sh mingw --prefix={target_prefix} ; fi',
			'if [ ! -f "already_configured_0" ] ; then sed -i.bak \'s/case \*       : option = -pthread ; libs = rt ;/case *      : option = -pthread ;/\' tools/build/src/tools/gcc.jam ; fi',
			'if [ ! -f "already_configured_0" ] ; then touch already_configured_0 ; fi',
			'if [ ! -f "already_ran_make_0" ] ; then echo "using gcc : mingw : {cross_prefix_bare}g++ : <rc>{cross_prefix_bare}windres <archiver>{cross_prefix_bare}ar <ranlib>{cross_prefix_bare}ranlib ;" > user-config.jam ; fi',
			'if [ ! -f "already_ran_make_0" ] ; then ./b2 toolset=gcc-mingw link=static threading=multi target-os=windows address-model=64 architecture=x86 --prefix={target_prefix} variant=release --with-system --with-filesystem --with-regex --with-date_time --with-thread --user-config=user-config.jam install ; fi',
			'if [ ! -f "already_ran_make_0" ] ; then touch already_ran_make_0 ; fi',
		),
		'_info' : { 'version' : '1.68.0', 'fancy_name' : 'Boost' },
	},
	'mujs' : {
		'repo_type' : 'git',
		'url' : 'git://git.ghostscript.com/mujs.git',
		# 'branch' : '3430d9a06d6f8a3696e2bbdca7681937e60ca7a9',
		'needs_configure' : False,
		'build_options': '{make_prefix_options} prefix={target_prefix} HAVE_READLINE=no',
		'install_options' : '{make_prefix_options} prefix={target_prefix} HAVE_READLINE=no',
		'patches' : [
			# ['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/mujs/mujs-0001-fix-building-with-mingw.patch', '-p1'],
			['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/mujs/mujs-0002-fix-install-with-mingw.patch', '-p1'],
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'mujs' },
	},
	'libjpeg-turbo' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/libjpeg-turbo/libjpeg-turbo.git',
		'conf_system' : 'cmake',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DENABLE_STATIC=ON -DENABLE_SHARED=OFF -DCMAKE_BUILD_TYPE=Release',
		'patches': [
			['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libjpeg-turbo/0001-libjpeg-turbo-git-mingw-compat.patch', '-p1'],
			['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libjpeg-turbo/0002-libjpeg-turbo-git-libmng-compat.patch', '-p1'],
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libjpeg-turbo' },
	},
	'libpng' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/libpng/files/libpng16/
			{ "url" : "https://sourceforge.net/projects/libpng/files/libpng16/1.6.35/libpng-1.6.35.tar.xz",	"hashes" : [ { "type" : "sha256", "sum" : "23912ec8c9584917ed9b09c5023465d71709dce089be503c7867fec68a93bcd7" },	], },
			{ "url" : "https://fossies.org/linux/misc/libpng-1.6.35.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "23912ec8c9584917ed9b09c5023465d71709dce089be503c7867fec68a93bcd7" }, ],	},
		],
		# 'custom_cflag' : '-fno-asynchronous-unwind-tables',
		'conf_system' : 'cmake',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF -DBUILD_BINARY=OFF -DCMAKE_BUILD_TYPE=Release -DPNG_TESTS=OFF -DPNG_SHARED=OFF -DPNG_STATIC=ON',
		# 'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --oldincludedir={target_prefix}/include',
		'patches' : [
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libpng/libpng-1.6.35-apng.patch', '-p1'),
		],
		'depends_on' : [ 'zlib', ],
		'_info' : { 'version' : '1.6.35', 'fancy_name' : 'libpng' },
	},
	'pcre2' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://ftp.pcre.org/pub/pcre/
			{ "url" : "https://ftp.pcre.org/pub/pcre/pcre2-10.32.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "9ca9be72e1a04f22be308323caa8c06ebd0c51efe99ee11278186cafbc4fe3af" }, ], },
			{ "url" : "https://fossies.org/linux/misc/pcre2-10.32.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "9ca9be72e1a04f22be308323caa8c06ebd0c51efe99ee11278186cafbc4fe3af" }, ], },
		],
		'conf_system' : 'cmake',
		'patches' : [
			['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/pcre2/0001-pcre2-iswild.patch', '-p1'],
		],
		'configure_options': '. {cmake_prefix_options} '
			'-DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release -DPCRE2_BUILD_TESTS=OFF '
			'-DPCRE2_BUILD_PCRE2_8=ON -DPCRE2_BUILD_PCRE2_16=ON -DPCRE2_BUILD_PCRE2_32=ON -DPCRE2_NEWLINE=ANYCRLF '
			'-DPCRE2_SUPPORT_UNICODE=ON -DPCRE2_SUPPORT_JIT=ON'
		,
		'depends_on' : [
			'bzip2', 'zlib', 'pcre',
		],
		'_info' : { 'version' : '10.32', 'fancy_name' : 'pcre2' },
	},
	'libressl' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/libressl-portable/portable.git',
		'folder_name' : 'libressl_git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared',
		'patches' : [
			# ( 'https://raw.githubusercontent.com/shinchiro/mpv-winbuild-cmake/master/packages/libressl-0001-ignore-compiling-test-and-man-module.patch', '-p1' ),
			# ( 'https://raw.githubusercontent.com/shinchiro/mpv-winbuild-cmake/master/packages/libressl-0002-tls-revert-Add-tls-tls_keypair.c-commit.patch', '-p1' ),
			# ( 'https://raw.githubusercontent.com/DeadSix27/misc_patches/master/libressl/libressl-0001-rename-timegm-for-mingw-compat.patch', '-p1' ),
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libressl' },
	},
	'libpsl' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/rockdaboot/libpsl.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --disable-runtime --disable-builtin',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libpsl' },
	},
	'mingw-libgnurx' : {
		'repo_type' : 'archive',
		'folder_name' : 'mingw-libgnurx-2.5.1',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/mingw/files/Other/UserContributed/regex/
			{ "url" : "https://sourceforge.net/projects/mingw/files/Other/UserContributed/regex/mingw-regex-2.5.1/mingw-libgnurx-2.5.1-src.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "7147b7f806ec3d007843b38e19f42a5b7c65894a57ffc297a76b0dcd5f675d76" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix}', # --disable-shared --enable-static --enable-fsect-man5
		'cpu_count' : '1', #...
		'needs_make' : False,
		'needs_make_install' : False,
		'run_post_configure' : [
			'make -f Makefile.mingw-cross-env -j 1 TARGET={target_host} bin_PROGRAMS= sbin_PROGRAMS= noinst_PROGRAMS= install-static'
			#'{cross_prefix_bare}ranlib libregex.a'
			#'make -f "Makefile.mingw-cross-env" libgnurx.a V=1'
		],
		'patches' : [
			( 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/mingw-libgnurx-static.patch', '-p1' ),
			( 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libgnurx-1-build-static-lib.patch', '-p1' ),
		],
		'_info' : { 'version' : '2.5.1', 'fancy_name' : 'mingw-libgnurx' },
	},
	'gettext' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://ftp.gnu.org/pub/gnu/gettext/?C=M;O=D
			{ "url" : "https://ftp.gnu.org/pub/gnu/gettext/gettext-0.19.8.1.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "105556dbc5c3fbbc2aa0edb46d22d055748b6f5c7cd7a8d99f8e7eb84e938be4" }, ], },
			{ "url" : "https://fossies.org/linux/misc/gettext-0.19.8.1.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "105556dbc5c3fbbc2aa0edb46d22d055748b6f5c7cd7a8d99f8e7eb84e938be4" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --enable-threads=posix --without-libexpat-prefix --without-libxml2-prefix CPPFLAGS=-DLIBXML_STATIC',
		'version' : '0.19.8.1',
		'_info' : { 'version' : '0.19.8.1', 'fancy_name' : 'gettext' },
		'depends_on' : [ 'iconv' ],
	},
	'libfile_local' : { # the local variant is for bootstrapping, please make sure to always keep both at the same commit, otherwise it could fail.
		'repo_type' : 'git',
		'branch' : '4091ea8660a4355b0379564dc901e06bdcdc8c50', #'42d9a8a34607e8b0336b4c354cd5e7e7692bfec7',
		'url' : 'https://github.com/file/file.git',
		'rename_folder' : 'libfile_local.git',
		'configure_options': '--prefix={target_prefix} --disable-shared --enable-static',
		'needs_make' : False,
		'env_exports' : { 'TARGET_CFLAGS' : '{original_cflags}' },
		'run_post_patch' : [ 'autoreconf -fiv' ],

	},
	'libfile' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/file/file.git',
		'branch' : '4091ea8660a4355b0379564dc901e06bdcdc8c50', #'42d9a8a34607e8b0336b4c354cd5e7e7692bfec7',
		'rename_folder' : 'libfile.git',
		'patches' : [
			( 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/file-win32.patch', '-p1' ),
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --enable-fsect-man5',
		'depends_on' : [ 'mingw-libgnurx', 'libfile_local' ],
		'env_exports' : { 'TARGET_CFLAGS' : '{original_cflags}' },
		'run_post_patch' : [ 'autoreconf -fiv' ],
		'flipped_path' : True,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'file' },
	},
	'libflac' : {
		'repo_type' : 'git',
		'url' : 'https://git.xiph.org/flac.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'depends_on': [
			'libogg',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'flac (library)' },
	},
	'libarchive': {
		'repo_type' : 'git',
		'url' : 'https://github.com/libarchive/libarchive.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-bsdtar --disable-bsdcat --disable-bsdcpio --without-openssl', #--without-xml2 --without-nettle
		'depends_on' : [
			'bzip2', 'expat', 'zlib', 'xz', 'lzo'
		],
		'run_post_install' : [
			'sed -i.bak \'s/Libs: -L${{libdir}} -larchive/Libs: -L${{libdir}} -larchive -llzma -lbcrypt/\' "{pkg_config_path}/libarchive.pc"', # libarchive complaints without this.
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libarchive' },
	},
	'lzo': {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://www.oberhumer.com/opensource/lzo/download/?C=M;O=D
			{ "url" : "http://www.oberhumer.com/opensource/lzo/download/lzo-2.10.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "c0f892943208266f9b6543b3ae308fab6284c5c90e627931446fb49b4221a072" }, ], },
			{ "url" : "https://fossies.org/linux/misc/lzo-2.10.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "c0f892943208266f9b6543b3ae308fab6284c5c90e627931446fb49b4221a072" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : '2.10', 'fancy_name' : 'lzo' },
	},
	'uchardet': {
		'repo_type' : 'git',
		'url' : 'https://anongit.freedesktop.org/git/uchardet/uchardet.git',
		# 'branch' : 'f136d434f0809e064ac195b5bc4e0b50484a474c', #master fails
		'conf_system' : 'cmake',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF -DBUILD_BINARY=OFF -DCMAKE_BUILD_TYPE=Release',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'uchardet' },
	},
	'libcdio' : {
		'repo_type' : 'git',
		'url' : 'git://git.savannah.gnu.org/libcdio.git', # old: http://git.savannah.gnu.org/cgit/libcdio.git/snapshot/libcdio-release-0.94.tar.gz
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-cddb --enable-cpp-progs --disable-shared --enable-static', #  --enable-maintainer-mode
		'run_post_patch' : (
			'touch doc/version.texi', # took me far to long to come up with and find this workaround
			'touch src/cd-info.1 src/cd-drive.1 src/iso-read.1 src/iso-info.1 src/cd-read.1', # .....
			#'if [ ! -f "configure" ] ; then ./autogen.sh ; fi',
			#'make -C doc stamp-vti', # idk why it needs this... odd thing: https://lists.gnu.org/archive/html/libcdio-devel/2016-03/msg00007.html
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libcdio' },
	},
	'libcdio-paranoia' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/rocky/libcdio-paranoia.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'depends_on': (
			'libcdio',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libcdio-paranoia' },
	},
	'libdvdcss' : {
		'repo_type' : 'git',
		'url' : 'https://code.videolan.org/videolan/libdvdcss.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-doc',
		'run_post_patch' : (
			'autoreconf -fiv',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libdvdcss' },
	},
	'libdvdread' : {
		'repo_type' : 'git',
		'url' : 'https://code.videolan.org/videolan/libdvdread.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --with-libdvdcss',
		'depends_on' : (
			'libdvdcss',
		),
		'run_post_patch' : (
			'autoreconf -fiv',
		),
		'run_post_install' : (
			'sed -i.bak \'s/-ldvdread/-ldvdread -ldvdcss/\' "{pkg_config_path}/dvdread.pc"', # fix undefined reference to `dvdcss_close'
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libdvdread' },
	},
	'libdvdnav' : {
		'repo_type' : 'git',
		'url' : 'https://code.videolan.org/videolan/libdvdnav.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --with-libdvdcss',
		'depends_on' : (
			'libdvdread',
		),
		'run_post_patch' : (
			'autoreconf -fiv',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libdvdnav' },
	},
	'libbluray' : {
		'repo_type' : 'git',
		'recursive_git' : True,
		'url' : 'https://git.videolan.org/git/libbluray.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-examples --disable-doxygen-doc --disable-bdjava-jar --enable-udf', #--without-libxml2 --without-fontconfig .. optional.. I guess
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libbluray_git_remove_strtok_s.patch', '-p1'),
		),
		'run_post_install' : (
			'sed -i.bak \'s/-lbluray.*$/-lbluray -lfreetype -lexpat -lz -lbz2 -lxml2 -lws2_32 -lgdi32 -liconv/\' "{pkg_config_path}/libbluray.pc"', # fix undefined reference to `xmlStrEqual' and co
		),
		'depends_on' : (
			'freetype', 'libcdio-paranoia'
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libbluray' },
	},
	'openal' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/kcat/openal-soft.git',
		# 'branch' : '46f18ba114831ff26e8f270c6b5c881b45838439',
		'conf_system' : 'cmake',
		# 'source_subfolder' : '_build',
		'custom_cflag' : '-O3', # native tools have to use the same march as end product else it fails*
		'configure_options':
			'. {cmake_prefix_options} -DCMAKE_TOOLCHAIN_FILE=XCompile.txt -DHOST={target_host}'
			' -DCMAKE_INSTALL_PREFIX={target_prefix} -DCMAKE_FIND_ROOT_PATH='
			' -DLIBTYPE=STATIC -DALSOFT_UTILS=OFF -DALSOFT_EXAMPLES=OFF',
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/openal/0001-versioned-w32-dll.mingw.patch', '-p1'),
			# ('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/openal/0002-w32ize-portaudio-loading.mingw.patch', '-p1'),
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/openal/0003-openal-not-32.mingw.patch', '-p1'),
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/openal/0004-disable-OSS-windows.patch', '-p1'),
		),
		'run_post_patch' : [
			"sed -i.bak 's/CMAKE_INSTALL_PREFIX \"\${{CMAKE_FIND_ROOT_PATH}}\"/CMAKE_INSTALL_PREFIX \"\"/' XCompile.txt",
		],
		'run_post_install' : [
			"sed -i.bak 's/^Libs: -L\\${{libdir}} -lopenal $/Libs: -L\\${{libdir}} -lopenal -lwinmm/' '{pkg_config_path}/openal.pc'", #issue with it not using pkg-config option "--static" or so idk?
		],
		'install_options' : 'DESTDIR={target_prefix}',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'openal-soft' },
	},
	'lcms2' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/mm2/Little-CMS.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'Little-CMS2' },
	},
	'python3_libs': {
		'repo_type' : 'git',
		'url' : 'https://github.com/DeadSix27/python_mingw_libs.git',
		'needs_configure' : False,
		'needs_make_install' : False,
		'build_options': 'PREFIX={target_prefix} GENDEF={mingw_binpath}/gendef DLLTOOL={mingw_binpath}/{cross_prefix_bare}dlltool PYTHON_VERSION=3.7.1',
		'_info' : { 'version' : '3.7.1', 'fancy_name' : 'Python (library-only)' },
	},
	'vapoursynth_libs': {
		'repo_type' : 'git',
		'url' : 'https://github.com/DeadSix27/vapoursynth_mingw_libs.git',
		'needs_configure' : False,
		'needs_make_install' : False,
		'depends_on' : [ 'python3_libs' ],
		'build_options': 'PREFIX={target_prefix} GENDEF={mingw_binpath}/gendef DLLTOOL={mingw_binpath}/{cross_prefix_bare}dlltool VAPOURSYNTH_VERSION=R45',
		'packages': {
			'arch' : [ '7za' ],
		},
		'_info' : { 'version' : 'R45', 'fancy_name' : 'VapourSynth (library-only)' },
	},
	'luajit': {
		'repo_type' : 'git',
		'url' : 'http://luajit.org/git/luajit-2.0.git',
		'needs_configure' : False,
		'custom_cflag' : '-O3', # doesn't like march's past ivybridge (yet), so we override it.
		'install_options' : 'CROSS={cross_prefix_bare} HOST_CC="gcc -m{bit_num}" TARGET_SYS=Windows BUILDMODE=static FILE_T=luajit.exe PREFIX={target_prefix}',
		'build_options': 'CROSS={cross_prefix_bare} HOST_CC="gcc -m{bit_num}" TARGET_SYS=Windows BUILDMODE=static amalg',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'LuaJIT2' },
	},
	'a52dec' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: http://liba52.sourceforge.net/
			{ "url" : "http://liba52.sourceforge.net/files/a52dec-0.7.4.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "a21d724ab3b3933330194353687df82c475b5dfb997513eef4c25de6c865ec33" }, ], },
			{ "url" : "https://gstreamer.freedesktop.org/src/mirror/a52dec-0.7.4.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "a21d724ab3b3933330194353687df82c475b5dfb997513eef4c25de6c865ec33" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static CFLAGS=-std=gnu89',
		'run_post_patch' : [
			'rm configure',
		],
		'build_options': 'bin_PROGRAMS= sbin_PROGRAMS= noinst_PROGRAMS=',
		'install_options': 'bin_PROGRAMS= sbin_PROGRAMS= noinst_PROGRAMS=',
		'_info' : { 'version' : '0.7.4', 'fancy_name' : 'a52dec' },
	},
	'amf_headers' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/DeadSix27/AMF',
		'rename_folder' : 'amd_media_framework_headers',
		"needs_configure": False,
		"needs_make": False,
		"needs_make_install": False,
		'run_post_patch' : (
			'if [ ! -f "already_done" ] ; then if [ ! -d "{target_prefix}/include/AMF" ]; then mkdir -p "{target_prefix}/include/AMF" ; fi ; fi',
			'if [ ! -f "already_done" ] ; then pwd ; fi',
			'if [ ! -f "already_done" ] ; then cp -av "amf/public/include/." "{target_prefix}/include/AMF" ; fi',
			'if [ ! -f "already_done" ] ; then touch  "already_done" ; fi',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'AMF (headers)' },
	},
	'nv-codec-headers' : {
		'repo_type' : 'git',
		'url' : 'https://git.videolan.org/git/ffmpeg/nv-codec-headers.git',
		"needs_configure": False,
		'build_options': 'PREFIX={target_prefix}',
		'install_options' : 'PREFIX={target_prefix}',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'nVidia (headers)' },
	},
	'libffmpeg' : {
		'repo_type' : 'git',
		'url' : 'git://git.ffmpeg.org/ffmpeg.git',
		'rename_folder' : 'libffmpeg_git',
		'configure_options': '!VAR(ffmpeg_base_config)VAR! --prefix={target_prefix} --disable-shared --enable-static --disable-doc --disable-programs --enable-amf',
		'depends_on': [ 'ffmpeg_depends' ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'FFmpeg (library)' },
	},
	'bzip2' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#{ "url" : "http://www.bzip.org/1.0.6/bzip2-1.0.6.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "a2848f34fcd5d6cf47def00461fcb528a0484d8edef8208d6d2e2909dc61d9cd" }, ], }, # Website is dead.
			{ "url" : "https://fossies.org/linux/misc/bzip2-1.0.6.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "a2848f34fcd5d6cf47def00461fcb528a0484d8edef8208d6d2e2909dc61d9cd" }, ], },
		],
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/bzip2/bzip2_cross_compile.diff', '-p0'),
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/bzip2/bzip2-1.0.6-gcc8.patch', '-p0'),
		),
		"needs_configure": False,
		"needs_make": True,
		"needs_make_install": False,
		'build_options': '{make_prefix_options} libbz2.a bzip2 bzip2recover install',
		'_info' : { 'version' : '1.0.6', 'fancy_name' : 'BZip2 (library)' },
	},
	'decklink_headers' : { # not gpl
		'repo_type' : 'none',
		'folder_name' : 'decklink_headers',
		'run_post_patch' : (
			'if [ ! -f "already_done" ] ; then wget https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/additional_headers/DeckLinkAPI.h ; fi',
			'if [ ! -f "already_done" ] ; then wget https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/additional_headers/DeckLinkAPI_i.c ; fi',
			'if [ ! -f "already_done" ] ; then wget https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/additional_headers/DeckLinkAPIVersion.h ; fi',
			'if [ ! -f "already_done" ] ; then cp -fv "DeckLinkAPI.h" "{target_prefix}/include/DeckLinkAPI.h" ; fi',
			'if [ ! -f "already_done" ] ; then cp -fv "DeckLinkAPI_i.c" "{target_prefix}/include/DeckLinkAPI_i.c" ; fi',
			'if [ ! -f "already_done" ] ; then cp -fv "DeckLinkAPIVersion.h" "{target_prefix}/include/DeckLinkAPIVersion.h" ; fi',
			'if [ ! -f "already_done" ] ; then touch  "already_done" ; fi',
		),
		'needs_make' : False,
		'needs_make_install' : False,
		'needs_configure' : False,
	},
	'zlib' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/madler/zlib.git',
		'env_exports' : {
			'AR' : '{cross_prefix_bare}ar',
			'CC' : '{cross_prefix_bare}gcc',
			'PREFIX' : '{target_prefix}',
			'RANLIB' : '{cross_prefix_bare}ranlib',
			'LD'     : '{cross_prefix_bare}ld',
			'STRIP'  : '{cross_prefix_bare}strip',
			'CXX'    : '{cross_prefix_bare}g++',
		},
		'configure_options': '--static --prefix={target_prefix}',
		'build_options': '{make_prefix_options} ARFLAGS=rcs',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'zlib' },
	},
	'xz' : { #lzma
		'repo_type' : 'git',
		'url' : 'https://github.com/xz-mirror/xz.git',
		#'url' : 'http://git.tukaani.org/xz.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-xz --disable-xzdec --disable-lzmadec --disable-lzmainfo --disable-doc',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'xz' },
	},
	'libzimg' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/sekrit-twc/zimg.git',
		#'branch' : 'd0f9cdebd34b0cb032f79357660bd0f6f23069ee', # '3aae2066e5b8df328866ba7e8636d8901f42e8e7',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'zimg' },
	},
	'libsnappy' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/google/snappy.git',
		'conf_system' : 'cmake',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF -DBUILD_BINARY=OFF -DSNAPPY_BUILD_TESTS=OFF -DCMAKE_BUILD_TYPE=Release',
		'run_post_install': (
			'rm -vf {target_prefix}/lib/libsnappy.dll.a',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libsnappy' },
	},
	'gmp' : {
		#export CC_FOR_BUILD=/usr/bin/gcc idk if we need this anymore, compiles fine without.
		#export CPP_FOR_BUILD=usr/bin/cpp
		#generic_configure "ABI=$bits_target"
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://gmplib.org/download/gmp/
			{ "url" : "https://gmplib.org/download/gmp/gmp-6.1.2.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "87b565e89a9a684fe4ebeeddb8399dce2599f9c9049854ca8c0dfbdea0e21912" }, ], },
			{ "url" : "https://fossies.org/linux/misc/gmp-6.1.2.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "87b565e89a9a684fe4ebeeddb8399dce2599f9c9049854ca8c0dfbdea0e21912" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : '6.1.2', 'fancy_name' : 'gmp' },
	},
	'libnettle' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://ftp.gnu.org/gnu/nettle/?C=M;O=D
			{ "url" : "https://ftp.gnu.org/gnu/nettle/nettle-3.4.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "ae7a42df026550b85daca8389b6a60ba6313b0567f374392e54918588a411e94" }, ], },
			{ "url" : "https://fossies.org/linux/privat/nettle-3.4.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "ae7a42df026550b85daca8389b6a60ba6313b0567f374392e54918588a411e94" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-openssl --with-included-libtasn1',
		'depends_on' : [
			'gmp',
		],
		'_info' : { 'version' : '3.4', 'fancy_name' : 'nettle' },
	},
	'iconv' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://ftp.gnu.org/pub/gnu/libiconv/?C=M;O=D
			{ "url" : "https://ftp.gnu.org/pub/gnu/libiconv/libiconv-1.15.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "ccf536620a45458d26ba83887a983b96827001e92a13847b45e4925cc8913178" }, ], },
			{ "url" : "https://fossies.org/linux/misc/libiconv-1.15.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "ccf536620a45458d26ba83887a983b96827001e92a13847b45e4925cc8913178" }, ], },
		],
		# CFLAGS=-O2
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-nls --enable-extra-encodings',
		'_info' : { 'version' : '1.15', 'fancy_name' : 'libiconv' },
	},
	'gnutls' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://www.gnupg.org/ftp/gcrypt/gnutls/v3.6/
			{ "url" : "https://www.gnupg.org/ftp/gcrypt/gnutls/v3.6/gnutls-3.6.4.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "c663a792fbc84349c27c36059181f2ca86c9442e75ee8b0ad72f5f9b35deab3a" }, ], },
			{ "url" : "https://fossies.org/linux/misc/gnutls-3.6.4.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "c663a792fbc84349c27c36059181f2ca86c9442e75ee8b0ad72f5f9b35deab3a" }, ], },
		],
		'configure_options':
			'--host={target_host} --prefix={target_prefix} --disable-shared --enable-static '
			'--disable-srp-authentication '
			'--disable-non-suiteb-curves '
			'--enable-cxx '
			'--enable-nls '
			'--disable-rpath '
			'--disable-gtk-doc '
			'--disable-guile '
			'--disable-doc '
			'--enable-local-libopts '
			# '--disable-guile '
			# '--disable-libdane '
			'--disable-tools '
			'--disable-tests '
			'--with-zlib '
			'--with-included-libtasn1 '
			'--with-included-unistring '
			'--with-default-trust-store-file '
			'--with-default-blacklist-file '
			'--without-tpm '
			'--without-p11-kit'
		,
		# 'configure_options':
			# '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --with-included-unistring '
			# '--disable-rpath --disable-nls --disable-guile --disable-doc --disable-tests --enable-local-libopts --with-included-libtasn1 --with-libregex-libs="-lgnurx" --without-p11-kit --disable-silent-rules '
			# 'CPPFLAGS="-DWINVER=0x0501 -DAI_ADDRCONFIG=0x0400 -DIPV6_V6ONLY=27" LIBS="-lws2_32" ac_cv_prog_AR="{cross_prefix_full}ar"'
		# ,
		'run_post_install': [
			"sed -i.bak 's/-lgnutls *$/-lgnutls -lnettle -lhogweed -lgmp -lcrypt32 -lws2_32 -liconv/' \"{pkg_config_path}/gnutls.pc\"", #TODO -lintl
		],
		# 'patches' : [
			# ('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/gnutls/0001-gnutls-3.5.11-arpainet_pkgconfig.patch', '-p1'),
			# ('https://raw.githubusercontent.com/Martchus/PKGBUILDs/master/gnutls/mingw-w64/gnutls-3.2.7-rpath.patch','-p1'),
			# ('https://raw.githubusercontent.com/Martchus/PKGBUILDs/master/gnutls/mingw-w64/gnutls-fix-external-libtasn1-detection.patch','-p1'),
		# ],
		'depends_on' : [
			'gmp',
			'libnettle',
		],
		# 'env_exports' : {
		'_info' : { 'version' : '3.6.4', 'fancy_name' : 'gnutls' },
	},
	'frei0r' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://files.dyne.org/frei0r/
			{ "url" : "https://files.dyne.org/frei0r/frei0r-plugins-1.6.1.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "e0c24630961195d9bd65aa8d43732469e8248e8918faa942cfb881769d11515e" }, ], },
			{ "url" : "https://ftp.osuosl.org/pub/blfs/conglomeration/frei0r/frei0r-plugins-1.6.1.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "e0c24630961195d9bd65aa8d43732469e8248e8918faa942cfb881769d11515e" }, ], },
		],
		'conf_system' : 'cmake',
		'run_post_patch': ( # runs commands post the patch process
			'sed -i.bak "s/find_package (Cairo)//g" CMakeLists.txt', #idk
		),
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DWITHOUT_OPENCV=YES',
		'_info' : { 'version' : '1.6.1', 'fancy_name' : 'frei0r-plugins' },
	},
	'libsndfile' : {
		'repo_type' : 'git',
		#'branch' : '81a71e08c09b20b0255aa66e40fce293008b9525', # 'd2ca7f4afc776d7c0c14c9a9a5ba94d9ae3affb8',
		'url' : 'https://github.com/erikd/libsndfile.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --enable-sqlite --disable-test-coverage --enable-external-libs --enable-experimental',
		#'patches' : [ #patches courtesy of https://github.com/Alexpux/MINGW-packages/tree/master/mingw-w64-libsndfile
			#('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libsndfile/0001-more-elegant-and-foolproof-autogen-fallback.all.patch', '-p0'),
			#('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libsndfile/0003-fix-source-searches.mingw.patch', '-p0'),
		#],
		'run_post_patch': [
			'autoreconf -fiv -I M4',
		],
		'run_post_install' : [
			'sed -i.bak \'s/Libs: -L${{libdir}} -lsndfile/Libs: -L${{libdir}} -lsndfile -lFLAC -lvorbis -lvorbisenc -logg -lspeex/\' "{pkg_config_path}/sndfile.pc"', #issue with rubberband not using pkg-config option "--static" or so idk?
		],
		'depends_on': [	'libspeex' ],
		'packages': {
			'arch' : [ 'autogen' ],
		},
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libsndfile' },
	},
	'libbs2b' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/bs2b/files/libbs2b/
			{ "url" : "https://sourceforge.net/projects/bs2b/files/libbs2b/3.1.0/libbs2b-3.1.0.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "6aaafd81aae3898ee40148dd1349aab348db9bfae9767d0e66e0b07ddd4b2528" }, ], },
			{ "url" : "http://sourceforge.mirrorservice.org/b/bs/bs2b/libbs2b/3.1.0/libbs2b-3.1.0.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "6aaafd81aae3898ee40148dd1349aab348db9bfae9767d0e66e0b07ddd4b2528" }, ], },
		],
		'env_exports' : {
			"ac_cv_func_malloc_0_nonnull" : "yes", # fixes undefined reference to `rpl_malloc'
		},
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : '3.1.0', 'fancy_name' : 'libbs2b' },
	},
	'wavpack' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/dbry/WavPack.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'wavpack' },
	},
	'libgme_game_music_emu' : {
		'repo_type' : 'git',
		'url' : 'https://bitbucket.org/mpyne/game-music-emu.git',
		'conf_system' : 'cmake',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF -DENABLE_UBSAN=OFF',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'game-music-emu' },
	},
	'libwebp' : {
		'repo_type' : 'git',
		'url' : 'https://chromium.googlesource.com/webm/libwebp',
		#'branch' : '082757087332f55c7daa5a869a19f1598d0be401', #old: e4eb458741f61a95679a44995c212b5f412cf5a1
		'run_post_patch': [
			'sed -i.bak "s/\$LIBPNG_CONFIG /\$LIBPNG_CONFIG --static /g" configure.ac', # fix building with libpng
			'autoreconf -fiv',
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --enable-swap-16bit-csp --enable-experimental --enable-libwebpmux --enable-libwebpdemux --enable-libwebpdecoder --enable-libwebpextras',
		'depends_on' : [ 'libpng', 'libjpeg-turbo' ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libwebp' },
	},
	'flite' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: http://www.speech.cs.cmu.edu/flite/packed/
			{ "url" : "http://ftp2.za.freebsd.org/pub/FreeBSD/ports/distfiles/flite-1.4-release.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "45c662160aeca6560589f78daf42ab62c6111dd4d244afc28118c4e6f553cd0c" }, ], },
			{ "url" : "http://www.speech.cs.cmu.edu/flite/packed/flite-1.4/flite-1.4-release.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "45c662160aeca6560589f78daf42ab62c6111dd4d244afc28118c4e6f553cd0c" }, ], },
		],
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/flite_64.diff', '-p0'),
		),
		'cpu_count' : '1',
		'needs_make_install' : False,
		'run_post_patch': (
			'sed -i.bak "s|i386-mingw32-|{cross_prefix_bare}|" configure',
			'sed -i "s|-DWIN32 -shared|-DWIN64 -static|" configure',
		),
		"run_post_build": (
			'mkdir -pv "{target_prefix}/include/flite"',
			'cp -fv include/* "{target_prefix}/include/flite"',
			'cp -fv ./build/{bit_name}-mingw32/lib/*.a "{target_prefix}/lib"',
		),
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : '1.4', 'fancy_name' : 'flite' },
	},
	'libgsm' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: http://www.quut.com/gsm
			{ "url" : "https://src.fedoraproject.org/repo/pkgs/gsm/gsm-1.0.18.tar.gz/sha512/c5b597f68d4a270e1d588f480dcde66fda8302564c687d753f2bd4fc41d246109243e567568da61eddce170f5232d869984743ddf1eea7696d673014a1a453b7/gsm-1.0.18.tar.gz",
				"hashes" : [ { "type" : "sha256", "sum" : "04f68087c3348bf156b78d59f4d8aff545da7f6e14f33be8f47d33f4efae2a10" }, ],
			},
			{ "url" : "http://www.quut.com/gsm/gsm-1.0.18.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "04f68087c3348bf156b78d59f4d8aff545da7f6e14f33be8f47d33f4efae2a10" }, ], },
		],
		'folder_name' : 'gsm-1.0-pl18',
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/gsm-1.0.16.patch', '-p0'),
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/gsm-1.0.16_Makefile.patch', '-p0'), # toast fails. so lets just patch it out of the makefile..
		),
		'needs_configure' : False,
		'needs_make_install' : False,
		"run_post_build": (
			'cp -fv lib/libgsm.a {target_prefix}/lib',
			'mkdir -pv {target_prefix}/include/gsm',
			'cp -fv inc/gsm.h {target_prefix}/include/gsm',
		),
		#'cpu_count' : '1',
		'build_options': '{make_prefix_options} INSTALL_ROOT={target_prefix}',
		'_info' : { 'version' : '1.0.18', 'fancy_name' : 'gsm' },
	},
	'davs2' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/pkuvcl/davs2.git',
		'source_subfolder' : 'build/linux',
		'configure_options': '--prefix={target_prefix} --host={target_host} --cross-prefix={cross_prefix_bare} --disable-cli',
		'install_target' : 'install-lib-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'davs2' },
	},
	'kvazaar' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/ultravideo/kvazaar.git',
		'configure_options': '--prefix={target_prefix} --host={target_host}',
		'run_post_patch': [
			'sed -i.bak "s/KVZ_PUBLIC const kvz_api/const kvz_api/g" src/kvazaar.h',
		],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'kvazaar' },
	},
	'openmpt' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/OpenMPT/openmpt.git',
		# 'source_subfolder' : '_build',
		'needs_configure' : False,
		'build_options': 'CONFIG=mingw64-win64 TEST=0 SHARED_LIB=0 STATIC_LIB=1 EXAMPLES=0 MODERN=1',
		'install_options': 'CONFIG=mingw64-win64 TEST=0 SHARED_LIB=0 STATIC_LIB=1 EXAMPLES=0 MODERN=1 PREFIX={target_prefix}',
		# 'configure_path' : '../build/autotools/configure',
		# 'run_post_patch' : [
			# '!SWITCHDIR|../build/autotools',
			# 'autoreconf -fiv',
			# '!SWITCHDIR|../../_build',
		# ],
		# 'configure_options': '--prefix={target_prefix} --host={target_host}',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'openmpt' },
	},
	'libopus' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/xiph/opus.git',
		'patches': (
			("https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/opus/opus_git_strip_declspec.patch", '-p1'),
		),
		'custom_cflag' : '-O3',
		'run_post_install': [
			'sed -i.bak \'s/Libs: -L${{libdir}} -lopus.*/Libs: -L${{libdir}} -lopus -lssp/\' "{pkg_config_path}/opus.pc"', # ???, keep checking whether this is needed, apparently it is for now.
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-silent-rules',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'opus' },
	},
	'opencore-amr' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/opencore-amr/files/opencore-amr/
			{ "url" : "https://sourceforge.net/projects/opencore-amr/files/opencore-amr/opencore-amr-0.1.5.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "2c006cb9d5f651bfb5e60156dbff6af3c9d35c7bbcc9015308c0aff1e14cd341" }, ], },
			{ "url" : "https://sourceforge.mirrorservice.org/o/op/opencore-amr/opencore-amr/opencore-amr-0.1.5.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "2c006cb9d5f651bfb5e60156dbff6af3c9d35c7bbcc9015308c0aff1e14cd341" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : '0.1.5', 'fancy_name' : 'opencore-amr' },
	},
	'vo-amrwbenc' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/opencore-amr/files/vo-amrwbenc/
			{ "url" : "https://pkgs.rpmfusion.org/repo/pkgs/free/vo-amrwbenc/vo-amrwbenc-0.1.3.tar.gz/f63bb92bde0b1583cb3cb344c12922e0/vo-amrwbenc-0.1.3.tar.gz",
				"hashes" : [ { "type" : "sha256", "sum" : "5652b391e0f0e296417b841b02987d3fd33e6c0af342c69542cbb016a71d9d4e"}, ],
			},
			{ "url" : "https://sourceforge.net/projects/opencore-amr/files/vo-amrwbenc/vo-amrwbenc-0.1.3.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "5652b391e0f0e296417b841b02987d3fd33e6c0af342c69542cbb016a71d9d4e" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : '0.1.3', 'fancy_name' : 'vo-amrwbenc' },
	},
	'libogg' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/xiph/ogg.git',
		# 'folder_name' : 'ogg-1.3.2',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ogg' },
	},
	'libspeexdsp' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/xiph/speexdsp.git',
		'run_post_patch' : [ 'autoreconf -fiv', ],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'speexdsp' },
	},
	'libspeex' : {
		'repo_type' : 'git', #"LDFLAGS=-lwinmm"
		'url' : 'https://github.com/xiph/speex.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'depends_on' : [ 'libogg', 'libspeexdsp', ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'speex' },
	},
	'libvorbis' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/xiph/vorbis.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'run_post_install': (
			'sed -i.bak \'s/Libs: -L${{libdir}} -lvorbisenc/Libs: -L${{libdir}} -lvorbisenc -lvorbis -logg/\' "{pkg_config_path}/vorbisenc.pc"', # dunno why ffmpeg doesnt work with Requires.private
			'sed -i.bak \'s/Libs: -L${{libdir}} -lvorbis/Libs: -L${{libdir}} -lvorbis -logg/\' "{pkg_config_path}/vorbis.pc"', # dunno why ffmpeg doesnt work with Requires.private
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'vorbis' },
	},
	'libtheora' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/xiph/theora.git',
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/theora_remove_rint_1.2.0alpha1.patch', '-p1'),
		),
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'theora' },
	},
	'freetype' : {
		'is_dep_inheriter' : True,
		'depends_on' : [ 'bzip2', 'freetype_lib', 'harfbuzz_lib-with-freetype', ], # 'freetype_lib-with-harfbuzz' ],
	},
	'harfbuzz' : {
		'is_dep_inheriter' : True,
		'depends_on' : [ 'bzip2', 'freetype_lib', 'harfbuzz_lib-with-freetype', ],
	},
	'harfbuzz_lib' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS https://www.freedesktop.org/software/harfbuzz/release/?C=M;O=D
			{ "url" : "https://www.freedesktop.org/software/harfbuzz/release/harfbuzz-2.1.3.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "613264460bb6814c3894e3953225c5357402915853a652d40b4230ce5faf0bee" }, ], },
			{ "url" : "https://fossies.org/linux/misc/harfbuzz-2.1.3.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "613264460bb6814c3894e3953225c5357402915853a652d40b4230ce5faf0bee" }, ], },
		],
		'run_post_install': [
			'sed -i.bak \'s/Libs: -L${{libdir}} -lharfbuzz.*/Libs: -L${{libdir}} -lharfbuzz -lfreetype/\' "{pkg_config_path}/harfbuzz.pc"',
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --without-freetype --with-fontconfig=no --disable-shared --with-icu=no --with-glib=no --with-gobject=no --disable-gtk-doc-html', #--with-graphite2 --with-cairo --with-icu --with-gobject
		'_info' : { 'version' : '2.1.3', 'fancy_name' : 'harfbuzz' },
	},
	'harfbuzz_lib-with-freetype' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS https://www.freedesktop.org/software/harfbuzz/release/?C=M;O=D
			{ "url" : "https://www.freedesktop.org/software/harfbuzz/release/harfbuzz-2.1.3.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "613264460bb6814c3894e3953225c5357402915853a652d40b4230ce5faf0bee" }, ], },
			{ "url" : "https://fossies.org/linux/misc/harfbuzz-2.1.3.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "613264460bb6814c3894e3953225c5357402915853a652d40b4230ce5faf0bee" }, ], },
		],
		'run_post_install': [
			'sed -i.bak \'s/Libs: -L${{libdir}} -lharfbuzz.*/Libs: -L${{libdir}} -lharfbuzz -lfreetype/\' "{pkg_config_path}/harfbuzz.pc"',
		],
		'folder_name' : 'harfbuzz-with-freetype',
		'rename_folder' : 'harfbuzz-with-freetype',
		'configure_options': '--host={target_host} --prefix={target_prefix} --with-freetype --with-fontconfig=no --disable-shared --with-icu=no --with-glib=no --with-gobject=no --disable-gtk-doc-html',
		'_info' : { 'version' : '2.1.3', 'fancy_name' : 'harfbuzz (with freetype2)' },
	},
	'freetype_lib-with-harfbuzz' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/freetype/files/freetype2/
			{ "url" : "https://fossies.org/linux/misc/freetype-2.9.1.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "db8d87ea720ea9d5edc5388fc7a0497bb11ba9fe972245e0f7f4c7e8b1e1e84d" }, ], },
			{ "url" : "https://sourceforge.net/projects/freetype/files/freetype2/2.9.1/freetype-2.9.1.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "db8d87ea720ea9d5edc5388fc7a0497bb11ba9fe972245e0f7f4c7e8b1e1e84d" }, ], },
		],
		'folder_name' : 'freetype-with-harfbuzz',
		'rename_folder' : 'freetype-with-harfbuzz',
		'configure_options': '--host={target_host} --build=x86_64-linux-gnu --prefix={target_prefix} --disable-shared --enable-static --with-zlib={target_prefix} --without-png --with-harfbuzz=yes',
		'run_post_install': (
			'sed -i.bak \'s/Libs: -L${{libdir}} -lfreetype.*/Libs: -L${{libdir}} -lfreetype -lbz2 -lharfbuzz/\' "{pkg_config_path}/freetype2.pc"',
		),
		'_info' : { 'version' : '2.9.1', 'fancy_name' : 'freetype2' },
	},
	'freetype_lib' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/freetype/files/freetype2/
			{ "url" : "https://fossies.org/linux/misc/freetype-2.9.1.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "db8d87ea720ea9d5edc5388fc7a0497bb11ba9fe972245e0f7f4c7e8b1e1e84d" }, ], },
			{ "url" : "https://sourceforge.net/projects/freetype/files/freetype2/2.9.1/freetype-2.9.1.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "db8d87ea720ea9d5edc5388fc7a0497bb11ba9fe972245e0f7f4c7e8b1e1e84d" }, ], },
		],
		'configure_options': '--host={target_host} --build=x86_64-linux-gnu --prefix={target_prefix} --disable-shared --enable-static --with-zlib={target_prefix} --without-png --with-harfbuzz=no',
		'_info' : { 'version' : '2.9.1', 'fancy_name' : 'freetype2' },
	},
	'expat' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://github.com/libexpat/libexpat/releases
			{ "url" : "https://github.com/libexpat/libexpat/releases/download/R_2_2_6/expat-2.2.6.tar.bz2",	"hashes" : [ { "type" : "sha256", "sum" : "17b43c2716d521369f82fc2dc70f359860e90fa440bea65b3b85f0b246ea81f2" },	], },
			{ "url" : "https://fossies.org/linux/www/expat-2.2.6.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "17b43c2716d521369f82fc2dc70f359860e90fa440bea65b3b85f0b246ea81f2" }, ],	},
		],
		'env_exports' : {
			'CPPFLAGS' : '-DXML_LARGE_SIZE',
		},
		'run_post_patch': (
			'sed -i.bak "s/SUBDIRS += xmlwf doc/SUBDIRS += xmlwf/" Makefile.am',
			'aclocal',
			'automake',
		),
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --without-docbook',
		'_info' : { 'version' : '2.2.6', 'fancy_name' : 'expat' },
	},
	'libxml2' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: http://xmlsoft.org/sources/?C=M;O=D
			{ "url" : "http://xmlsoft.org/sources/libxml2-2.9.8.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "0b74e51595654f958148759cfef0993114ddccccbb6f31aee018f3558e8e2732" }, ], },
			{ "url" : "https://fossies.org/linux/www/libxml2-2.9.8.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "0b74e51595654f958148759cfef0993114ddccccbb6f31aee018f3558e8e2732" }, ], },
		],
		'folder_name' : 'libxml2-2.9.8',
		'rename_folder' : 'libxml2-2.9.8-rc1',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --without-python --enable-tests=no --enable-programs=no',
		# 'patches' : [ #todo remake this patch
			# ('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/libxml2/0001-libxml2-2.9.4-add_prog_test_toggle.patch', '-p1'),
		# ],
		'run_post_patch' : [
			'autoreconf -fiv',
		],
		'run_post_install' : (
			'sed -i.bak \'s/Libs: -L${{libdir}} -lxml2/Libs: -L${{libdir}} -lxml2 -lz -llzma -liconv -lws2_32/\' "{pkg_config_path}/libxml-2.0.pc"', # libarchive complaints without this.
		),
		'depends_on': [
			'xz', 'iconv'
		],
		'_info' : { 'version' : '2.9.8-rc1', 'fancy_name' : 'libxml2' },
	},
	'libxvid' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://labs.xvid.com/
			{ "url" : "http://downloads.xvid.org/downloads/xvidcore-1.3.5.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "165ba6a2a447a8375f7b06db5a3c91810181f2898166e7c8137401d7fc894cf0" }, ], },
			{ "url" : "https://fossies.org/linux/misc/xvidcore-1.3.5.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "165ba6a2a447a8375f7b06db5a3c91810181f2898166e7c8137401d7fc894cf0" }, ], },
		],
		'folder_name' : 'xvidcore',
		'rename_folder' : 'xvidcore-1.3.5',
		'source_subfolder': 'build/generic',
		'configure_options': '--host={target_host} --prefix={target_prefix}',
		# 'cpu_count' : '1',
		'run_post_configure': (
			'sed -i.bak "s/-mno-cygwin//" platform.inc',
		),
		'run_post_install': (
			'rm -v {target_prefix}/lib/xvidcore.dll.a',
			'mv -v {target_prefix}/lib/xvidcore.a {target_prefix}/lib/libxvidcore.a',
		),
		'_info' : { 'version' : '1.3.5', 'fancy_name' : 'xvidcore' },
	},
	'xavs' : {
		#LDFLAGS='-lm'
		'repo_type' : 'svn',
		'url' : 'svn://svn.code.sf.net/p/xavs/code/trunk',
		'folder_name' : 'xavs_svn',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --cross-prefix={cross_prefix_bare}',
		'run_post_install' : (
			'rm -f NUL', # uh???
		),
		'packages': {
			'arch' : [ 'yasm' ],
		},
		'_info' : { 'version' : 'svn (master)', 'fancy_name' : 'xavs' },
	},
	'xavs2' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/pkuvcl/xavs2.git',
		'source_subfolder': 'build/linux',
		'configure_options': '--prefix={target_prefix} --host={target_host} --cross-prefix={cross_prefix_bare} --disable-cli',
		'install_target' : 'install-lib-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'xavs2' },
	},
	'libsoxr' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/soxr/files/
			{ "url" : "https://download.videolan.org/contrib/soxr/soxr-0.1.3-Source.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "b111c15fdc8c029989330ff559184198c161100a59312f5dc19ddeb9b5a15889" }, ], },
			{ "url" : "https://sourceforge.net/projects/soxr/files/soxr-0.1.3-Source.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "b111c15fdc8c029989330ff559184198c161100a59312f5dc19ddeb9b5a15889" }, ], },
		],
		'conf_system' : 'cmake',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DHAVE_WORDS_BIGENDIAN_EXITCODE=0 -DBUILD_SHARED_LIBS:bool=off -DBUILD_TESTS:BOOL=OFF -DCMAKE_AR={cross_prefix_full}ar', #not sure why it cries about AR
		'_info' : { 'version' : '0.1.3', 'fancy_name' : 'soxr' },
	},
	'libebur128' : { # uneeded
		'repo_type' : 'git',
		'url' : 'https://github.com/jiixyj/libebur128.git',
		'configure_options': '. {cmake_prefix_options} -DENABLE_INTERNAL_QUEUE_H:BOOL=ON -DCMAKE_AR={cross_prefix_full}ar', #not sure why it cries about AR
		'conf_system' : 'cmake',
		'run_post_patch': (
			'sed -i.bak \'s/ SHARED / STATIC /\' ebur128/CMakeLists.txt',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libebur128' },
	},
	'libx265' : {
		'repo_type' : 'mercurial',
		'url' : 'https://bitbucket.org/multicoreware/x265',
		'rename_folder' : 'libx265_hg',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DENABLE_ASSEMBLY=ON -DENABLE_CLI:BOOL=OFF -DENABLE_SHARED=OFF -DCMAKE_AR={cross_prefix_full}ar', # no cli, as this is just for the library.
		'conf_system' : 'cmake',
		'source_subfolder': 'source',
		'run_post_install' : [
			'sed -i.bak \'s|-lmingwex||g\' "{pkg_config_path}/x265.pc"',
		],
		'_info' : { 'version' : 'mercurial (default)', 'fancy_name' : 'x265 (library)' },
	},
	'libx265_multibit' : {
		'repo_type' : 'mercurial',
		'url' : 'https://bitbucket.org/multicoreware/x265',
		'rename_folder' : 'libx265_hg_multibit',
		'source_subfolder': 'source',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_AR={cross_prefix_full}ar -DENABLE_ASSEMBLY=ON -DENABLE_SHARED=OFF -DENABLE_CLI:BOOL=OFF -DEXTRA_LIB="x265_main10.a;x265_main12.a" -DEXTRA_LINK_FLAGS="-L{offtree_prefix}/libx265_10bit/lib;-L{offtree_prefix}/libx265_12bit/lib" -DLINKED_10BIT=ON -DLINKED_12BIT=ON -DCMAKE_INSTALL_PREFIX={target_prefix}',
		'conf_system' : 'cmake',
		'run_post_build' : [
			'mv -vf libx265.a libx265_main.a',
			'cp -vf {offtree_prefix}/libx265_10bit/lib/libx265_main10.a libx265_main10.a',
			'cp -vf {offtree_prefix}/libx265_12bit/lib/libx265_main12.a libx265_main12.a',
			'"{cross_prefix_full}ar" -M <<EOF\nCREATE libx265.a\nADDLIB libx265_main.a\nADDLIB libx265_main10.a\nADDLIB libx265_main12.a\nSAVE\nEND\nEOF',
		],
		'run_post_install' : [
			'sed -i.bak \'s|-lmingwex||g\' "{pkg_config_path}/x265.pc"',
		],
		'depends_on' : [ 'libx265_multibit_10', 'libx265_multibit_12' ],
		# 'patches': [ # for future reference
		# 	[ 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/x265/0001-Remove_exports.patch', '-p1', '..' ],
		# ],
		'_info' : { 'version' : 'mercurial (default)', 'fancy_name' : 'x265 (multibit library 12/10/8)' },
	},
	'libx265_multibit_10' : {
		'repo_type' : 'mercurial',
		'url' : 'https://bitbucket.org/multicoreware/x265',
		'rename_folder' : 'libx265_hg_10bit',
		'source_subfolder' : 'source',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_AR={cross_prefix_full}ar -DENABLE_ASSEMBLY=ON -DHIGH_BIT_DEPTH=ON -DEXPORT_C_API=OFF -DENABLE_SHARED=OFF -DENABLE_CLI=OFF -DCMAKE_INSTALL_PREFIX={offtree_prefix}/libx265_10bit',
		'run_post_install' : [
			'mv -vf "{offtree_prefix}/libx265_10bit/lib/libx265.a" "{offtree_prefix}/libx265_10bit/lib/libx265_main10.a"'
		],
		'conf_system' : 'cmake',
		'_info' : { 'version' : 'mercurial (default)', 'fancy_name' : 'x265 (library (10))' },
	},
	'libx265_multibit_12' : {
		'repo_type' : 'mercurial',
		'url' : 'https://bitbucket.org/multicoreware/x265',
		'rename_folder' : 'libx265_hg_12bit',
		'source_subfolder' : 'source',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_AR={cross_prefix_full}ar -DENABLE_ASSEMBLY=ON -DHIGH_BIT_DEPTH=ON -DEXPORT_C_API=OFF -DENABLE_SHARED=OFF -DENABLE_CLI=OFF -DMAIN12=ON -DCMAKE_INSTALL_PREFIX={offtree_prefix}/libx265_12bit',
		'run_post_install' : [
			'mv -vf "{offtree_prefix}/libx265_12bit/lib/libx265.a" "{offtree_prefix}/libx265_12bit/lib/libx265_main12.a"'
		],
		'conf_system' : 'cmake',
		'_info' : { 'version' : 'mercurial (default)', 'fancy_name' : 'x265 (library (12))' },
	},
	'libopenh264' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/cisco/openh264.git',
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/openh264/0001-remove-fma3-call.patch','-p1'),
		),
		'needs_configure' : False,
		'build_options': '{make_prefix_options} OS=mingw_nt ARCH={bit_name} ASM=yasm',
		'install_options': '{make_prefix_options} OS=mingw_nt',
		'install_target' : 'install-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'openh264' },
	},
	'vamp_plugin' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://vamp-plugins.org/develop.html
			{ "url" : "https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/sources/vamp-plugin-sdk-2.7.1.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "c6fef3ff79d2bf9575ce4ce4f200cbf219cbe0a21cfbad5750e86ff8ae53cb0b" }, ], },
			{ "url" : "https://code.soundsoftware.ac.uk/attachments/download/2206/vamp-plugin-sdk-2.7.1.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "c6fef3ff79d2bf9575ce4ce4f200cbf219cbe0a21cfbad5750e86ff8ae53cb0b" }, ], },
		],
		'run_post_patch': (
			'cp -v build/Makefile.mingw64 Makefile',
		),
		'patches' : (
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/vamp-plugin-sdk-2.7.1.patch','-p0'), #They rely on M_PI which is gone since c99 or w/e, give them a self defined one and hope for the best.
		),
		'build_options': '{make_prefix_options} sdkstatic', # for DLL's add 'sdk rdfgen'
		'needs_make_install' : False, # doesnt s support xcompile installing
		'run_post_build' : ( # lets install it manually then I guess?
			'cp -v libvamp-sdk.a "{target_prefix}/lib/"',
			'cp -v libvamp-hostsdk.a "{target_prefix}/lib/"',
			'cp -rv vamp-hostsdk/ "{target_prefix}/include/"',
			'cp -rv vamp-sdk/ "{target_prefix}/include/"',
			'cp -rv vamp/ "{target_prefix}/include/"',
			'cp -v pkgconfig/vamp.pc.in "{target_prefix}/lib/pkgconfig/vamp.pc"',
			'cp -v pkgconfig/vamp-hostsdk.pc.in "{target_prefix}/lib/pkgconfig/vamp-hostsdk.pc"',
			'cp -v pkgconfig/vamp-sdk.pc.in "{target_prefix}/lib/pkgconfig/vamp-sdk.pc"',
			'sed -i.bak \'s/\%PREFIX\%/{target_prefix_sed_escaped}/\' "{pkg_config_path}/vamp.pc"',
			'sed -i.bak \'s/\%PREFIX\%/{target_prefix_sed_escaped}/\' "{pkg_config_path}/vamp-hostsdk.pc"',
			'sed -i.bak \'s/\%PREFIX\%/{target_prefix_sed_escaped}/\' "{pkg_config_path}/vamp-sdk.pc"',
		),
		'_info' : { 'version' : '2.7.1', 'fancy_name' : 'vamp-plugin-sdk' },
	},
	'fftw3' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: http://fftw.org/download.html
			{ "url" : "http://fftw.org/fftw-3.3.8.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "6113262f6e92c5bd474f2875fa1b01054c4ad5040f6b0da7c03c98821d9ae303" }, ], },
			{ "url" : "https://fossies.org/linux/misc/fftw-3.3.8.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "6113262f6e92c5bd474f2875fa1b01054c4ad5040f6b0da7c03c98821d9ae303" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : '3.3.8', 'fancy_name' : 'fftw3' },
	},
	'sdl2' : {
		'folder_name' : 'sdl2_merc',
		'repo_type' : 'mercurial',
		'source_subfolder' : '_build',
		'url' : 'https://hg.libsdl.org/SDL',
		'configure_path' : '../configure',
		'run_post_patch' : [
			'sed -i.bak "s/ -mwindows//" ../configure',
		],
		# SDL2 patch superseded per https://hg.libsdl.org/SDL/rev/117d4ce1390e
		#'patches' : (
		#	('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/sdl2/0001-SDL2_hg.xinput_state_ex.patch', '-p1', '..'),
		#),
		# 'custom_cflag' : '-DDECLSPEC=', # avoid SDL trac tickets 939 and 282, and not worried about optimizing yet...
		"run_post_install": (
			'sed -i.bak "s/  -lmingw32 -lSDL2main -lSDL2 /  -lmingw32 -lSDL2main -lSDL2  -ldinput8 -ldxguid -ldxerr8 -luser32 -lgdi32 -lwinmm -limm32 -lole32 -loleaut32 -lshell32 -lversion -luuid/" "{pkg_config_path}/sdl2.pc"', # allow ffmpeg to output anything to console :|
			#'sed -i.bak "s/-mwindows/-ldinput8 -ldxguid -ldxerr8 -luser32 -lgdi32 -lwinmm -limm32 -lole32 -loleaut32 -lshell32 -lversion -luuid/" "{target_prefix}/bin/sdl2-config"', # update this one too for good measure, FFmpeg can use either, not sure which one it defaults to...
			'cp -v "{target_prefix}/bin/sdl2-config" "{cross_prefix_full}sdl2-config"', # this is the only mingw dir in the PATH so use it for now [though FFmpeg doesn't use it?]
		),
		'configure_options': '--prefix={target_prefix} --host={target_host} --disable-shared --enable-static',
		'_info' : { 'version' : 'mercurial (default)', 'fancy_name' : 'SDL2' },
	},
	'libsamplerate' : {
		'repo_type' : 'git',
		#'branch' : '7dcc9bb727dae4e2010cdc6ef7cda101b05509a4',
		'url' : 'https://github.com/erikd/libsamplerate.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-alsa',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libsamplerate' },
		'depends_on' : [
			'libflac',
			'fftw3',
		],
	},
	'librubberband' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/breakfastquay/rubberband.git',
		'download_header' : (
			'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/additional_headers/ladspa.h',
		),
		'env_exports' : {
			'AR' : '{cross_prefix_bare}ar',
			'CC' : '{cross_prefix_bare}gcc',
			'PREFIX' : '{target_prefix}',
			'RANLIB' : '{cross_prefix_bare}ranlib',
			'LD'     : '{cross_prefix_bare}ld',
			'STRIP'  : '{cross_prefix_bare}strip',
			'CXX'    : '{cross_prefix_bare}g++',
		},
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'build_options': '{make_prefix_options}',
		'needs_make_install' : False,
		'run_post_build' : (
			'cp lib/* "{target_prefix}/lib"',
			'cp -r rubberband "{target_prefix}/include"',
			'cp rubberband.pc.in "{pkg_config_path}/rubberband.pc"',
			'sed -i.bak "s|%PREFIX%|{target_prefix_sed_escaped}|" "{pkg_config_path}/rubberband.pc"',
			'sed -i.bak \'s/-lrubberband *$/-lrubberband -lfftw3 -lsamplerate -lstdc++/\' "{pkg_config_path}/rubberband.pc"',
		),
		'depends_on': [
			'libsndfile',
		],
		'_info' : { 'version' : '1.8.1', 'fancy_name' : 'librubberband' },
	},
	'liblame' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/lame/files/lame/
			{ "url" : "https://sourceforge.net/projects/lame/files/lame/3.100/lame-3.100.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e" }, ], },
			{ "url" : "https://fossies.org/linux/misc/lame-3.100.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --enable-nasm --disable-frontend',
		'_info' : { 'version' : '3.10', 'fancy_name' : 'LAME (library)' },
	},
	'twolame' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://github.com/njh/twolame/releases/
			{ "url" : "https://github.com/njh/twolame/releases/download/0.3.13/twolame-0.3.13.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "98f332f48951f47f23f70fd0379463aff7d7fb26f07e1e24e42ddef22cc6112a" }, ], },
			{ "url" : "https://sourceforge.net/projects/twolame/files/twolame/0.3.13/twolame-0.3.13.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "98f332f48951f47f23f70fd0379463aff7d7fb26f07e1e24e42ddef22cc6112a" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static CPPFLAGS=-DLIBTWOLAME_STATIC',
		'_info' : { 'version' : '0.3.13', 'fancy_name' : 'twolame' },
	},
	'vidstab' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/georgmartius/vid.stab.git', #"Latest commit 97c6ae2  on May 29, 2015" .. master then I guess?
		'conf_system' : 'cmake',
		'configure_options': '{cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DENABLE_SHARED=OFF -DCMAKE_AR={cross_prefix_full}ar -DUSE_OMP=OFF', #fatal error: omp.h: No such file or directory
		'run_post_patch': (
			'sed -i.bak "s/SHARED/STATIC/g" CMakeLists.txt',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'vid.stab' },
	},
	'libmysofa' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/hoene/libmysofa',
		#'branch' : '16d77ad6b4249c3ba3b812d26c4cbb356300f908',
		'source_subfolder' : '_build',
		'conf_system' : 'cmake',
		'configure_options': '.. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS:bool=off -DBUILD_TESTS=no',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libmysofa' },
	},
	'libcaca' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/cacalabs/libcaca.git',
		'run_post_configure': (
			'sed -i.bak "s/int vsnprintf/int vnsprintf_disabled/" "caca/string.c"',
			'sed -i.bak "s/int vsnprintf/int vnsprintf_disabled/" "caca/figfont.c"',
			'sed -i.bak "s/__declspec(dllexport)//g" cxx/caca++.h',
			'sed -i.bak "s/__declspec(dllexport)//g" caca/caca.h',
			'sed -i.bak "s/__declspec(dllexport)//g" caca/caca0.h',
			'sed -i.bak "s/__declspec(dllimport)//g" caca/caca.h',
			'sed -i.bak "s/__declspec(dllimport)//g" caca/caca0.h',
		),
		'run_post_install': [
			"sed -i.bak 's/-lcaca *$/-lcaca -lz/' \"{pkg_config_path}/caca.pc\"",
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --libdir={target_prefix}/lib --disable-cxx --disable-csharp --disable-java --disable-python --disable-ruby --disable-imlib2 --disable-doc --disable-examples',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libcaca' },
	},
	'libmodplug' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/modplug-xmms/files/libmodplug/
			{ "url" : "https://ftp.openbsd.org/pub/OpenBSD/distfiles/libmodplug-0.8.9.0.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "457ca5a6c179656d66c01505c0d95fafaead4329b9dbaa0f997d00a3508ad9de" }, ], },
			{ "url" : "https://sourceforge.net/projects/modplug-xmms/files/libmodplug/0.8.9.0/libmodplug-0.8.9.0.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "457ca5a6c179656d66c01505c0d95fafaead4329b9dbaa0f997d00a3508ad9de" }, ], },
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --enable-static --disable-shared',
		'run_post_install': (
			# unfortunately this sed isn't enough, though I think it should be [so we add --extra-libs=-lstdc++ to FFmpegs configure] https://trac.ffmpeg.org/ticket/1539
			'sed -i.bak \'s/-lmodplug.*/-lmodplug -lstdc++/\' "{pkg_config_path}/libmodplug.pc"', # huh ?? c++?
			#'sed -i.bak \'s/__declspec(dllexport)//\' "{target_prefix}/include/libmodplug/modplug.h"', #strip DLL import/export directives
			#'sed -i.bak \'s/__declspec(dllimport)//\' "{target_prefix}/include/libmodplug/modplug.h"',
		),
		'_info' : { 'version' : '0.8.9.0', 'fancy_name' : 'libmodplug' },
	},
	'zvbi' : {
		'repo_type' : 'archive',
		'download_locations' : [
			#UPDATECHECKS: https://sourceforge.net/projects/zapping/files/zvbi/
			{ "url" : "https://sourceforge.net/projects/zapping/files/zvbi/0.2.35/zvbi-0.2.35.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "fc883c34111a487c4a783f91b1b2bb5610d8d8e58dcba80c7ab31e67e4765318" }, ], },
			{ "url" : "https://download.videolan.org/contrib/zvbi/zvbi-0.2.35.tar.bz2", "hashes" : [ { "type" : "sha256", "sum" : "fc883c34111a487c4a783f91b1b2bb5610d8d8e58dcba80c7ab31e67e4765318" }, ], },
		],
		'env_exports' : {
			'LIBS' : '-lpng',
		},
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-dvb --disable-bktr --disable-nls --disable-proxy --without-doxygen',
		'make_subdir' : 'src',
		'patches': (
		    ('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/zvbi/0001-zvbi-0.2.35_win32.patch', '-p1'),
			('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/zvbi/0002-zvbi-0.2.35_ioctl.patch', '-p1'),
		),
		#sed -i.bak 's/-lzvbi *$/-lzvbi -lpng/' "$PKG_CONFIG_PATH/zvbi.pc"
		'run_post_build' : (
			'pwd',
			'cp -rv "../zvbi-0.2.pc" "{target_prefix}/lib/pkgconfig/zvbi-0.2.pc"',
		),
		'_info' : { 'version' : '0.2.35', 'fancy_name' : 'zvbi' },
	},
	'libilbc' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/dekkers/libilbc.git',
		'run_post_patch': [
			'autoreconf -fiv',
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libilbc' },
	},
	'libvpx' : {
		'repo_type' : 'git',
		'url' : 'https://chromium.googlesource.com/webm/libvpx',
		'configure_options':
			'--target={bit_name2}-{bit_name_win}-gcc '
			'--prefix={target_prefix} --disable-shared '
			'--enable-static --enable-webm-io --enable-vp9 '
			'--enable-vp8 --enable-runtime-cpu-detect '
			'--enable-vp9-highbitdepth --enable-vp9-postproc --enable-coefficient-range-checking '
			'--enable-error-concealment --enable-better-hw-compatibility '
			'--enable-multi-res-encoding --enable-vp9-temporal-denoising '
			'--disable-tools --disable-docs --disable-examples --disable-install-docs --disable-unit-tests --disable-decode-perf-tests --disable-encode-perf-tests --as=yasm'
		,
		'env_exports' : {
			'CROSS' : '{cross_prefix_bare}',
		},
		'custom_cflag' : '-fno-asynchronous-unwind-tables',
		'patches': (
			( 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/vpx_160_semaphore.patch', '-p1' ),
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libvpx' },
	},
	'fontconfig' : {
		'repo_type' : 'git',
		'do_not_bootstrap' : True,
		'cpu_count' : '1', # I had strange build issues with multiple threads..
		'branch' : '2bd559f75d76b514f789e32c5cc9643fd7c1e9a2', #'648e0cf3d5a53efeab93b24ae37490427d05229d',
		'url' : 'https://gitlab.freedesktop.org/fontconfig/fontconfig.git',
		'folder_name' : 'fontconfig_git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --enable-libxml2 --disable-shared --enable-static --disable-docs --disable-silent-rules',
		'patches' : [
			['https://raw.githubusercontent.com/DeadSix27/misc_patches/master/fontconfig/0001-fontconfig-remove-tests.patch', '-p1' ],
			['https://raw.githubusercontent.com/DeadSix27/misc_patches/master/fontconfig/fontconfig-git-utimes.patch', '-p1' ],
			# ['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/fontconfig/fontconfig-0001-fix-missing-bracket.patch', '-p1' ],
		],
		'run_post_patch': [
			'autoreconf -fiv',
		],
		'run_post_install': (
			'sed -i.bak \'s/-L${{libdir}} -lfontconfig[^l]*$/-L${{libdir}} -lfontconfig -lfreetype -lharfbuzz -lxml2 -liconv -lintl/\' "{pkg_config_path}/fontconfig.pc"',
		),
		'depends_on' : [
			'iconv','libxml2','freetype',
		],
		'packages': {
			'arch' : [ 'gperf' ],
		},
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'fontconfig' },
	},
	'libfribidi' : {
		#https://raw.githubusercontent.com/rdp/ffmpeg-windows-build-helpers/master/patches/fribidi.diff
		'repo_type' : 'git',
		'do_not_bootstrap' : True,
		'patches' : [
			[ 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/fribidi/0001-mingwcompat-remove-doc-tests.patch', '-p1' ],
		],
		'run_post_patch': [
			'autoreconf -fiv',
		],
		#'branch' : 'c8fb314d9cab3e4803054eb9829373f014684dc0', # 'b534ab2642f694c3106d5bc8d0a8beae60bf60d3',
		'url' : 'https://github.com/fribidi/fribidi.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-docs',
		'_info' : { 'version' : '1.0.1', 'fancy_name' : 'libfribidi' },
	},
	'libass' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/libass/libass.git',
		'patches' : [
			[ 'https://github.com/libass/libass/pull/298.patch' , '-p1' ], # Use FriBiDi 1.x API when available # for testing.
		],
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --enable-silent-rules',
		'run_post_install': (
			'sed -i.bak \'s/-lass -lm/-lass -lfribidi -lfreetype -lexpat -lm/\' "{pkg_config_path}/libass.pc"', #-lfontconfig
		),
		'depends_on' : [ 'fontconfig', 'harfbuzz', 'libfribidi', 'freetype', 'iconv', ],
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libass' },
	},
	'libopenjpeg' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/uclouvain/openjpeg.git',
		'conf_system' : 'cmake',
		'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS:bool=off',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'openjpeg' },
	},
	'intel_quicksync_mfx' : {
		'repo_type' : 'git',
		'do_not_bootstrap' : True,
		'run_post_patch': [
			'autoreconf -fiv',
		],
		'patches' :	[
			[ 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/mfx/mfx-0001-mingwcompat-disable-va.patch', '-p1' ],
		],
		'url' : 'https://github.com/lu-zero/mfx_dispatch.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --without-libva_drm --without-libva_x11',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'intel_quicksync_mfx' },
	},
	'fdk_aac' : {
		'repo_type' : 'git',
		'run_post_patch': [
			'autoreconf -fiv',
		],
		'url' : 'https://github.com/mstorsjo/fdk-aac.git',
		'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'fdk-aac' },
	},
	'rtmpdump' : {
		'repo_type' : 'git',
		'url' : 'https://git.ffmpeg.org/rtmpdump.git',
		'needs_configure': False,
		# doesn't compile with openssl1.1
		'install_options': 'SYS=mingw CRYPTO=GNUTLS LIB_GNUTLS="-L{target_prefix}/lib -lgnutls -lhogweed -lnettle -lgmp -lcrypt32 -lz" OPT=-O2 CROSS_COMPILE={cross_prefix_bare} SHARED=no prefix={target_prefix}',
		'build_options': 'SYS=mingw CRYPTO=GNUTLS LIB_GNUTLS="-L{target_prefix}/lib -lgnutls -lhogweed -lnettle -lgmp -lcrypt32 -lz"	 OPT=-O2 CROSS_COMPILE={cross_prefix_bare} SHARED=no prefix={target_prefix}',
		# 'install_options' : 'SYS=mingw CRYPTO=GNUTLS OPT=-O2 CROSS_COMPILE={cross_prefix_bare} SHARED=no prefix={target_prefix} LIB_GNUTLS="-L{target_prefix}/lib -lgnutls -lnettle -lhogweed -lgmp -lcrypt32 -lws2_32 -liconv -lz -lintl -liconv"',
		# 'build_options': 'SYS=mingw CRYPTO=GNUTLS OPT=-O2 CROSS_COMPILE={cross_prefix_bare} SHARED=no prefix={target_prefix} LIB_GNUTLS="-L{target_prefix}/lib -lgnutls -lnettle -lhogweed -lgmp -lcrypt32 -lws2_32 -liconv -lz -lintl -liconv"',
		'run_post_install':(
			'sed -i.bak \'s/-lrtmp -lz/-lrtmp -lwinmm -lz/\' "{pkg_config_path}/librtmp.pc"',
		),
		'depends_on' : (
			'gnutls',
		),
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'rtmpdump' },
	},
	'libx264' : {
		'repo_type' : 'git',
		'url' : 'https://git.videolan.org/git/x264.git',
		'rename_folder' : 'libx264_git',
		'configure_options': '--host={target_host} --enable-static --cross-prefix={cross_prefix_bare} --prefix={target_prefix} --enable-strip --disable-lavf --disable-cli',
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'x264 (library)' },
	},
	'libdav1d' : {
		'repo_type' : 'git',
		'url' : 'https://code.videolan.org/videolan/dav1d.git',
		'conf_system' : 'meson',
		'build_system' : 'ninja',
		'rename_folder' : 'libdav1d_git',
		'source_subfolder' : 'build',
		'configure_options':
			'--prefix={target_prefix} '
			'--libdir={target_prefix}/lib '
			'--default-library=static '
			'--buildtype=plain '
			'--backend=ninja '
			'-Dbuild_tests=false '
			'-Dbuild_tools=false '
			'--buildtype=release '
			'--cross-file={meson_env_file} ./ ..'
      ,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'dav1d (library)' },
	},
	'libaom' : {
		'repo_type' : 'git',
		'url' : 'https://aomedia.googlesource.com/aom',
		'branch' : '9284af62c37d62117c007d100e0442f144220ab8',
		'conf_system' : 'cmake',
		'source_subfolder' : 'build',
		'configure_options': '.. {cmake_prefix_options} '
			'-DCMAKE_INSTALL_PREFIX={target_prefix} '
			'-DCONFIG_LOWBITDEPTH=0 -DCONFIG_HIGHBITDEPTH=1 '
			'-DCONFIG_AV1=1 -DHAVE_PTHREAD=1 -DBUILD_SHARED_LIBS=0 -DENABLE_DOCS=0 -DCONFIG_INSTALL_DOCS=0 '
			'-DCONFIG_INSTALL_BINS=0 -DCONFIG_INSTALL_LIBS=1 '
			'-DCONFIG_INSTALL_SRCS=1 -DCONFIG_UNIT_TESTS=0 -DENABLE_TESTS=0 -DENABLE_TESTDATA=0 '
			'-DCONFIG_AV1_DECODER=1 -DCONFIG_AV1_ENCODER=1 '
			'-DCONFIG_MULTITHREAD=1 -DCONFIG_PIC=1 -DCONFIG_COEFFICIENT_RANGE_CHECKING=0 '
			'-DCONFIG_RUNTIME_CPU_DETECT=1 -DCONFIG_WEBM_IO=1 '
			'-DCONFIG_SPATIAL_RESAMPLING=1 -DENABLE_NASM=off'
      ,
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libaom' },
	},
	'libssh2' : {
		'repo_type' : 'git',
		'url' : 'https://github.com/libssh2/libssh2.git',
		'configure_options':
			'--host={target_host} '
			'--prefix={target_prefix} '
			'--disable-shared '
			'--enable-static '
			'--disable-examples-build '
			# '--with-crypto=openssl'
		,
		'depends_on': (
			'zlib', #'libressl'
		),
		'env_exports' : {
			'LIBS' : '-lcrypt32' # Otherwise: libcrypto.a(e_capi.o):e_capi.c:(.text+0x476d): undefined reference to `__imp_CertFreeCertificateContext'
		},
		'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libssh2' },
	},
	# ############################################################################################################
	# ############################################################################################################
	# ## Most of these deps I haven't used/updated in a  long while, most if not all probably stopped building. ##
	# ############################################################################################################
	# ############################################################################################################
	#'netcdf' : {
	#	'repo_type' : 'archive',
	#	'download_locations' : [
	#		{ "url" : "ftp://ftp.unidata.ucar.edu/pub/netcdf/netcdf-4.6.1.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "89c7957458740b763ae828c345240b8a1d29c2c1fed0f065f99b73181b0b2642" }, ], },
	#		{ "url" : "https://fossies.org/linux/misc/netcdf-4.6.1.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "89c7957458740b763ae828c345240b8a1d29c2c1fed0f065f99b73181b0b2642" }, ], },
	#	],
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-netcdf-4 --disable-dap',
	#	'_info' : { 'version' : '4.6.1', 'fancy_name' : 'netcdf' },
	#},
	#'orc' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://gstreamer.freedesktop.org/src/orc/orc-0.4.28.tar.xz',
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
	#	'_info' : { 'version' : '0.4.28', 'fancy_name' : 'orc' },
	#},
	#'libschroedinger' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://download.videolan.org/contrib/schroedinger/schroedinger-1.0.11.tar.gz',
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
	#	'run_post_configure': (
	#		'sed -i.bak \'s/testsuite//\' Makefile',
	#	),
	#	'run_post_install': (
	#		'sed -i.bak \'s/-lschroedinger-1.0$/-lschroedinger-1.0 -lorc-0.4/\' "{pkg_config_path}/schroedinger-1.0.pc"',
	#	),
	#	'depends_on' : [ 'orc' ],
	#	'_info' : { 'version' : '1.0.11', 'fancy_name' : 'schroedinger' },
    #
	#},
	#'liblzma' : {
	#	 'repo_type' : 'archive',
	#	 'custom_cflag': '',
	#	 'url' : 'https://tukaani.org/xz/xz-5.2.3.tar.bz2',
	#	 'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
	#	 '_info' : { 'version' : '5.2.3', 'fancy_name' : 'lzma' },
	# },
	#'lua' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://www.lua.org/ftp/lua-5.3.4.tar.gz',
	#	'needs_configure' : False,
	#	'build_options': 'CC={cross_prefix_bare}gcc PREFIX={target_prefix} RANLIB={cross_prefix_bare}ranlib LD={cross_prefix_bare}ld STRIP={cross_prefix_bare}strip CXX={cross_prefix_bare}g++ AR="{cross_prefix_bare}ar rcu" mingw', # LUA_A=lua53.dll LUA_T=lua.exe LUAC_T=luac.exe
	#	'install_options' : 'TO_BIN="lua.exe luac.exe lua53.dll" TO_LIB="liblua.a" INSTALL_TOP="{target_prefix}"', #TO_LIB="liblua.a liblua.dll.a"
	#	'install_target' : 'install',
	#	'packages': {
	#		'ubuntu' : [ 'lua5.2' ],
	#	},
	#	'_info' : { 'version' : '5.3.4', 'fancy_name' : 'lua' },
	#},
	#'sdl1' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://www.libsdl.org/release/SDL-1.2.15.tar.gz',
	#	'custom_cflag' : '-DDECLSPEC=',# avoid SDL trac tickets 939 and 282, and not worried about optimizing yet...
	#	"run_post_install": (
	#		'sed -i.bak "s/-mwindows//" "{pkg_config_path}/sdl.pc"', # allow ffmpeg to output anything to console :|
	#		'sed -i.bak "s/-mwindows//" "{target_prefix}/bin/sdl-config"', # update this one too for good measure, FFmpeg can use either, not sure which one it defaults to...
	#		'cp -v "{target_prefix}/bin/sdl-config" "{cross_prefix_full}sdl-config"', # this is the only mingw dir in the PATH so use it for now [though FFmpeg doesn't use it?]
	#	),
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
	#	'_info' : { 'version' : '1.2.15', 'fancy_name' : 'SDL1' },
	#},
	#'sdl2_archive' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://www.libsdl.org/release/SDL2-2.0.7.zip',
	#	# 'patches' : (
	#	# 	('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/sdl2/0001-SDL2-2.0.5.xinput.diff', '-p0'),
	#	# ),
	#	'custom_cflag' : '-DDECLSPEC=', # avoid SDL trac tickets 939 and 282, and not worried about optimizing yet...
	#	"run_post_install": (
	#		# 'sed -i.bak "s/-mwindows/-ldinput8 -ldxguid -ldxerr8 -luser32 -lgdi32 -lwinmm -limm32 -lole32 -loleaut32 -lshell32 -lversion -luuid/" "{pkg_config_path}/sdl2.pc"', # allow ffmpeg to output anything to console :|
	#		# 'sed -i.bak "s/-mwindows/-ldinput8 -ldxguid -ldxerr8 -luser32 -lgdi32 -lwinmm -limm32 -lole32 -loleaut32 -lshell32 -lversion -luuid/" "{target_prefix}/bin/sdl2-config"', # update this one too for good measure, FFmpeg can use either, not sure which one it defaults to...
	#		'cp -v "{target_prefix}/bin/sdl2-config" "{cross_prefix_full}sdl2-config"',
	#	),
	#	'configure_options': '--prefix={target_prefix} --host={target_host} --disable-shared --enable-static',
	#	'_info' : { 'version' : '2.0.7', 'fancy_name' : 'SDL2' },
	#},
	#'libcaca_old' : {
	#	'repo_type' : 'archive',
	#	'run_post_configure': (
	#		'sed -i.bak "s/int vsnprintf/int vnsprintf_disabled/" "caca/string.c"',
	#		'sed -i.bak "s/int vsnprintf/int vnsprintf_disabled/" "caca/figfont.c"',
	#		'sed -i.bak "s/__declspec(dllexport)//g" cxx/caca++.h',
	#		'sed -i.bak "s/__declspec(dllexport)//g" caca/caca.h',
	#		'sed -i.bak "s/__declspec(dllexport)//g" caca/caca0.h',
	#		'sed -i.bak "s/__declspec(dllimport)//g" caca/caca.h',
	#		'sed -i.bak "s/__declspec(dllimport)//g" caca/caca0.h',
	#	),
	#	'run_post_install': [
	#		"sed -i.bak 's/-lcaca *$/-lcaca -lz/' \"{pkg_config_path}/caca.pc\"",
	#	],
	#	'url' : 'https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/sources/libcaca-0.99.beta19.tar.gz',
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --libdir={target_prefix}/lib --disable-cxx --disable-csharp --disable-java --disable-python --disable-ruby --disable-imlib2 --disable-doc --disable-examples',
	#	'_info' : { 'version' : '0.99.beta19', 'fancy_name' : 'libcaca' },
	#},
	#'p11-kit' : {
	#	'repo_type' : 'archive',
	#	'needs_make_install' : False,
	#	'url' : 'hhttps://github.com/p11-glue/p11-kit/releases/download/0.23.9/p11-kit-0.23.9.tar.gz',
	#	'configure_options': '--host={target_host} --prefix={target_prefix}',
	#	'depends_on' : [ 'libtasn1', 'libffi' ],
	#	'env_exports' : {
	#		'LIBS' : '-liconv' # Otherwise: libcrypto.a(e_capi.o):e_capi.c:(.text+0x476d): undefined reference to `__imp_CertFreeCertificateContext'
	#	},
	#	'_info' : { 'version' : '0.23.9', 'fancy_name' : 'p11-kit' },
	#},
	#'libtasn1' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://ftp.gnu.org/gnu/libtasn1/libtasn1-4.13.tar.gz',
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-doc',
	#	'run_post_patch' : [
	#		'autoreconf -fiv',
	#	],
	#	'_info' : { 'version' : '4.13', 'fancy_name' : 'libtasn1' },
	#},
	#'libffi' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://sourceware.org/pub/libffi/libffi-3.2.1.tar.gz',
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --disable-doc',
	#	'_info' : { 'version' : '3.2.1', 'fancy_name' : 'libffi' },
	#},
	#'openssl_1_1' : {
	#	'repo_type' : 'archive',
	#	'download_locations' : [
	#		{ "url" : "https://www.openssl.org/source/openssl-1.1.1-pre8.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "1205cd763dd92c910cc590658a5b0774599e8587d89d6debd948f242b949321e" }, ], },
	#		{ "url" : "http://ftp.vim.org/pub/ftp/security/openssl/openssl-1.1.1-pre8.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "1205cd763dd92c910cc590658a5b0774599e8587d89d6debd948f242b949321e" }, ], },
	#	],
	#	'configure_options' : '{bit_name3} enable-capieng  --prefix={target_prefix} --openssldir={target_prefix}/ssl --cross-compile-prefix={cross_prefix_bare} no-shared no-asm',
	#	'configure_path' : './Configure',
	#	'install_target' : 'install_sw', # we don't need the docs..
	#	'build_options' : 'all',
	#	'env_exports' : {
	#		'CROSS_COMPILE' : '{cross_prefix_bare}',
	#	},
	#	'run_post_install' : [
	#		'sed -i.bak \'s/Libs: -L${{libdir}} -lcrypto/Libs: -L${{libdir}} -lcrypto -lcrypt32/\' "{pkg_config_path}/libcrypto.pc"', # libssh2 doesn't use --static pkgconfig, so we have to do this.
	#		'sed -i.bak \'s/Libs: -L${{libdir}} -lssl/Libs: -L${{libdir}} -lssl -lcrypt32/\' "{pkg_config_path}/libssl.pc"', # nor does curl
	#	],
	#	'_info' : { 'version' : '1.1.1-pre1', 'fancy_name' : 'openssl' },
	#},
	#'zenlib' : {
	#	'repo_type' : 'git',
	#	# 'branch' : 'v0.4.35',
	#	'source_subfolder' : 'Project/GNU/Library',
	#	'url' : 'https://github.com/MediaArea/ZenLib.git',
	#	'configure_options' : '--host={target_host} --prefix={target_prefix} --enable-static --disable-shared --enable-shared=no',
	#	'run_post_configure' : [
	#		'sed -i.bak \'s/ -DSIZE_T_IS_LONG//g\' Makefile',
	#	],
	#	# 'patches' : (
	#		# ('fcurl_gitibzen-1-fixes.patch', '-p1','../../..'),
	#	# ),
	#	# 'run_post_patch' : [
	#		# 'sed -i.bak \'/#include <windows.h>/ a\#include <time.h>\' ../../../Source/ZenLib/Ztring.cpp',
	#	# ],
	#	'_info' : { 'version' : 'git (v4.35)', 'fancy_name' : 'zenlib' },
	#},
	#'libfilezilla' : {
	#	'repo_type' : 'svn',
	#	'folder_name' : 'libfilezilla_svn',
	#	'url' : 'https://svn.filezilla-project.org/svn/libfilezilla/trunk',
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
	#	'run_post_patch' : [
	#		'autoreconf -fiv',
	#	],
	#	'env_exports' : {
	#		'CXXFLAGS' : '-O0',
	#	},
	#	'_info' : { 'version' : 'svn (master)', 'fancy_name' : 'FileZilla (libary)' },
	#},
	#'freeglut' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://downloads.sourceforge.net/project/freeglut/freeglut/3.0.0/freeglut-3.0.0.tar.gz',
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static',
	#	'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF -DENABLE_STATIC_RUNTIME=ON -DFREEGLUT_GLES=OFF -DFREEGLUT_BUILD_DEMOS=OFF -DFREEGLUT_REPLACE_GLUT=ON -DFREEGLUT_BUILD_STATIC_LIBS=ON -DFREEGLUT_BUILD_SHARED_LIBS=OFF',
	#	'conf_system' : 'cmake',
	#	'_info' : { 'version' : '3.0', 'fancy_name' : 'FreeGLUT (libary?)' },
	#},
    #
	#'wxwidgets' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://github.com/wxWidgets/wxWidgets/releases/download/v3.1.1/wxWidgets-3.1.1.tar.bz2',
	#	'configure_options':
	#		' --host={target_host} --build=x86_64-unknown-linux-gnu --prefix={target_sub_prefix} --disable-shared --enable-static --build='
	#		' --with-msw --with-opengl --disable-mslu --enable-unicode --with-regex=builtin --disable-precomp-headers'
	#		' --enable-graphics_ctx --enable-webview --enable-mediactrl --with-libpng=sys --with-libxpm=builtin --with-libjpeg=sys'
	#		' --with-libtiff=builtin --without-mac --without-dmalloc --without-wine --with-sdl --with-themes=all --disable-stl --enable-threads --enable-gui'
	#	,
	#	# 'run_post_install' : [
	#	# 	'cp -fv "{target_sub_prefix}/bin/wxrc-3.0" "{target_sub_prefix}/bin/wxrc"',
	#	# ],
	#	# 'patches' : [
	#	# 	('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/wxwidgets/0001-wxWidgets-c++11-PR2222.patch','-p1'),
	#	# ],
	#	# 'env_exports': {
	#	# 	'CXXFLAGS' : '-std=gnu++11',
	#	# 	'CXXCPP' : '{cross_prefix_bare}g++ -E -std=gnu++11',
	#	# },
	#	'_info' : { 'version' : '3.1.1', 'fancy_name' : 'wxWidgets (libary)' },
	#	'depends_on' : [ 'libjpeg-turbo', 'libpng', 'zlib' ],
	#},
	#'ca-bundles' : {
	#	'repo_type' : 'git',
	#	'url' : 'https://github.com/DeadSix27/mingw_ca_bundle_script.git',
	#	'needs_configure' : False,
	#	'needs_make_install' : False,
	#	'build_options': 'PREFIX={target_prefix}',
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ca-bundles' },
	#},
	#'librsvg' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://download.gnome.org/sources/librsvg/2.41/librsvg-2.42.3.tar.xz',
	#	'configure_options':
	#		'--host={target_host} '
	#		'--prefix={target_prefix} '
	#		'--disable-shared '
	#		'--enable-static '
	#	,
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'librsvg' },
	#},
	#'cppunit' : {
	#	'repo_type' : 'git',
	#	'url' : 'git://anongit.freedesktop.org/git/libreoffice/cppunit',
	#	'configure_options':
	#		'--host={target_host} '
	#		'--prefix={target_prefix} '
	#		'--disable-shared '
	#		'--enable-static '
	#	,
	#	'patches' : [
	#		['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/cppunit/Add-define-guard-for-NOMINMAX.patch','-p1']
	#	],
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'cppunit' },
	#},
	#'opencv' : { # not working yet
	#	'repo_type' : 'archive',
	#	'url' : 'https://github.com/opencv/opencv/archive/3.4.1.tar.gz',
	#	'folder_name' : 'opencv-3.4.1',
	#	'source_subfolder' : 'build',
	#	'configure_options': '.. -G"Unix Makefiles" -DCMAKE_SKIP_RPATH=ON -DBUILD_TESTS=OFF -DBUILD_opencv_world=ON -DBUILD_PERF_TESTS=OFF -DBUILD_DOCS=OFF -DBUILD_opencv_apps=OFF -DWITH_FFMPEG=OFF -DINSTALL_C_EXAMPLES=OFF -DINSTALL_PYTHON_EXAMPLES=OFF -DBUILD_JASPER=OFF -DBUILD_OPENEXR=OFF -DWITH_VTK=OFF -DWITH_IPP=OFF -DWITH_DSHOW=OFF -DENABLE_PRECOMPILED_HEADERS=OFF -DENABLE_STATIC_RUNTIME=OFF -DCMAKE_BUILD_TYPE=RELEASE -DCMAKE_INSTALL_PREFIX={target_prefix} -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_RANLIB={cross_prefix_full}ranlib -DCMAKE_C_COMPILER={cross_prefix_full}gcc -DCMAKE_CXX_COMPILER={cross_prefix_full}g++ -DCMAKE_RC_COMPILER={cross_prefix_full}windres -DCMAKE_FIND_ROOT_PATH={target_prefix}',
	#	'conf_system' : 'cmake',
	#	# 'patches' : [
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0001-mingw-w64-cmake.patch', '-p1', '..'],
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0002-solve_deg3-underflow.patch', '-p1', '..'],
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0003-issue-4107.patch', '-p1', '..'],
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0004-generate-proper-pkg-config-file.patch', '-p1', '..'],
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0005-opencv-support-python-3.6.patch', '-p1', '..'],
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0008-mingw-w64-cmake-lib-path.patch', '-p1', '..'],
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0009-openblas-find.patch', '-p1', '..'],
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0010-find-libpng-header.patch', '-p1', '..'],
	#		# ['https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-opencv/0011-dshow-build-fix.patch', '-p1', '..'],
	#	# ],
	#	'build_options' : 'VERBOSE=1',
	#	'install_options' : '{make_prefix_options} prefix={target_prefix} install',
	#	'_info' : { 'version' : '3.4.1', 'fancy_name' : 'opencv' },
	#},
	# 'taglib' : { # unused
	# 	'repo_type' : 'archive',
	# 	'url' : 'http://taglib.org/releases/taglib-1.11.1.tar.gz',
	# 	'conf_system' : 'cmake',
	# 	'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF -DENABLE_STATIC_RUNTIME=ON -DWITH_MP4=ON -DWITH_ASF=ON',
	# },
	#'libmediainfo' : {
	#	'repo_type' : 'git',
	#	'branch' : 'v0.7.94',
	#	'source_subfolder' : 'Project/GNU/Library',
	#	'url' : 'https://github.com/MediaArea/MediaInfoLib.git',
	#	'configure_options' : '--host={target_host} --prefix={target_prefix} --enable-shared --enable-static --with-libcurl --with-libmms --with-libmediainfo-name=MediaInfo.dll', # --enable-static --disable-shared --enable-shared=no
	#	'run_post_patch' : [
	#		'sed -i.bak \'s/Windows.h/windows.h/\' ../../../Source/MediaInfo/Reader/Reader_File.h',
	#		'sed -i.bak \'s/Windows.h/windows.h/\' ../../../Source/MediaInfo/Reader/Reader_File.cpp',
	#	],
	#	'run_post_configure' : [
	#		'sed -i.bak \'s/ -DSIZE_T_IS_LONG//g\' Makefile',
	#	],
	#	'depends_on': [
	#		'zenlib', 'libcurl',
	#	],
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libmediainfo' },
	#},
	#'libsqlite3' : {
	#	'repo_type' : 'archive',
	#	'download_locations' : [
	#		{ "url" : "https://www.sqlite.org/2018/sqlite-autoconf-3240000.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "d9d14e88c6fb6d68de9ca0d1f9797477d82fc3aed613558f87ffbdbbc5ceb74a" }, ], },
	#		{ "url" : "https://fossies.org/linux/misc/sqlite-autoconf-3240000.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "d9d14e88c6fb6d68de9ca0d1f9797477d82fc3aed613558f87ffbdbbc5ceb74a" }, ], },
	#	],
	#	'cflag_addition' : '-fexceptions -DSQLITE_ENABLE_COLUMN_METADATA=1 -DSQLITE_USE_MALLOC_H=1 -DSQLITE_USE_MSIZE=1 -DSQLITE_DISABLE_DIRSYNC=1 -DSQLITE_ENABLE_RTREE=1 -fno-strict-aliasing',
	#	'configure_options': '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --enable-threadsafe --disable-editline --enable-readline --enable-json1 --enable-fts5 --enable-session',
	#	'depends_on': (
	#		'zlib',
	#	),
	#	'_info' : { 'version' : '3.24.0', 'fancy_name' : 'libsqlite3' },
	#},
	#'libcurl' : {
	#	'repo_type' : 'git',
	#	'url' : 'https://github.com/curl/curl',
	#	'rename_folder' : 'curl_git',
	#	'configure_options': '--enable-static --disable-shared --target={bit_name2}-{bit_name_win}-gcc --host={target_host} --build=x86_64-linux-gnu --with-libssh2 --with-gnutls --prefix={target_prefix} --exec-prefix={target_prefix}',
	#	'patches' : [
	#		['https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/curl/0001-fix-build-with-libressl.patch', '-p1' ],
	#	],
	#	'depends_on': (
	#		'zlib','libssh2',
	#	),
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'libcurl' },
	#},
	#'angle_headers' : {
	#	'repo_type' : 'git',
	#	'url' : 'https://github.com/google/angle.git',
	#	'folder_name' : 'angle_headers_git',
	#	'needs_make':False,
	#	'needs_make_install':False,
	#	'needs_configure':False,
	#	'run_post_patch': [
	#		'if [ ! -f "already_done" ] ; then cp -rv "include/EGL" "{target_prefix}/include/" ; fi',
	#		'if [ ! -f "already_done" ] ; then cp -rv "include/KHR" "{target_prefix}/include/" ; fi',
	#		'if [ ! -f "already_done" ] ; then touch already_done ; fi',
	#	],
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ANGLE headers' },
	#},
	#'angle' : {
	#	'repo_type' : 'git',
	#	'url' : 'https://chromium.googlesource.com/angle/angle',
	#	'patches' : (
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/0002-Cross-compile-hacks.patch'                             ,'-p1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/0003-rename-sprintf_s.patch'                                ,'-p1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/0004-string_utils-cpp.patch'                                ,'-p1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/angle-0002-install-fixed.patch'                             ,'-p1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/angle/angle-0003-add-option-for-targeting-cpu-architecture.patch' ,'-p1'),
	#	),
	#	'needs_make':False,
	#	'needs_make_install':False,
	#	'needs_configure':False,
	#	'run_post_patch': (
	#		'if [ ! -f "already_done" ] ; then sed -i \'s/\'python\'/\'python2\'/\' gyp/warnings.gyp ; fi',
	#		'if [ ! -f "already_done" ] ; then make uninstall PREFIX={target_prefix} ; fi',
	#		'if [ ! -f "already_done" ] ; then make uninstall PREFIX={target_prefix} ; fi',
	#		'if [ ! -f "already_done" ] ; then cmake -E remove_directory build ; fi',
	#		'if [ ! -f "already_done" ] ; then gyp -Duse_ozone=0 -DOS=win -Dangle_gl_library_type=static_library -Dangle_use_commit_id=1 --depth . -I gyp/common.gypi src/angle.gyp --no-parallel --format=make --generator-output=build -Dangle_enable_vulkan=0 -Dtarget_cpu=x64 ; fi',
	#		'if [ ! -f "already_done" ] ; then make -C build/ commit_id ; fi',
	#		'if [ ! -f "already_done" ] ; then cmake -E copy build/out/Debug/obj/gen/angle/id/commit.h src/id/commit.h ; fi',
	#		'if [ ! -f "already_done" ] ; then make -C build {make_prefix_options} BUILDTYPE=Debug {make_cpu_count} ; fi',
	#		'if [ ! -f "already_done" ] ; then chmod u+x ./move-libs.sh && ./move-libs.sh {bit_name}-w64-mingw32 Debug ; fi',
	#		'if [ ! -f "already_done" ] ; then make install PREFIX={target_prefix} ; fi',
	#		'if [ ! -f "already_done" ] ; then touch already_done ; fi',
	#	),
	#	'packages': {
	#		'arch' : [ 'gyp' ],
	#	},
	#	'_info' : { 'version' : 'git (master)', 'fancy_name' : 'ANGLE' },
	#},
	## Still not building correctly.
	##
	## Build needs around 40G, install around 10-15Gb;
	## Make sure you have at least 60GB free when building,
	## you can delete the entire source folder of qt after install to free space up again,
	## then just uncomment the "\'_already_built\' : True," line below in the qt5 block, so building will be skipped each time.
	#'qt5' : {
	#	 # '_already_built' : True,
	#	'warnings' : [
	#		'Qt5 building CAN fail sometimes with multiple threads.. so if this failed try re-running it',
	#		'For more information see: https://bugreports.qt.io/browse/QTBUG-53393',
	#		'(You could add \'cpu_count\' : \'1\', to the config of QT5 if the slower speed is acceptable for you)',
	#		'---------------',
	#		'Build needs around 40G, install around 10-15Gb.',
	#		'Make sure you have at least 60GB free when building,',
	#		'you can delete the entire source folder of qt after install to free space up again,',
	#		'then just uncomment the "\'_already_built\' : True," line in the qt5 block, so building will be skipped each time.'
	#	],
	#	'env_exports' : {
	#		'CFLAGS'   : '-DDBUS_STATIC_BUILD -DJAS_DLL=0',
	#		#'CXXFLAGS' : '-DGRAPHITE2_STATIC',
	#		'PKG_CONFIG' : '{cross_prefix_full}pkg-config',
	#		'PKG_CONFIG_SYSROOT_DIR' : '/',
	#		'PKG_CONFIG_LIBDIR' : '{target_prefix}/lib/pkgconfig',
	#		'CROSS_COMPILE' : '{cross_prefix_bare}',
	#		'CROSS_target_prefix' : '{target_sub_prefix}',
	#		#'OPENSSL_LIBS' : '!CMD({cross_prefix_full}pkg-config --libs-only-l openssl)CMD!',
	#	},
	#	'cpu_count' : '1',
	#	'clean_post_configure' : False,
	#	'repo_type' : 'archive',
	#	'download_locations' : [
	#		{ "url" : "https://download.qt.io/official_releases/qt/5.10/5.10.1/single/qt-everywhere-src-5.10.1.tar.xz", "hashes" : [ { "type" : "sha256", "sum" : "05ffba7b811b854ed558abf2be2ddbd3bb6ddd0b60ea4b5da75d277ac15e740a" }, ], },
	#	],
	#	'configure_options' :
	#		'-static'
	#		' -no-iconv'
	#		' -no-sqlite'
	#		' -skip qtconnectivity'
	#		' -skip qtserialbus'
	#		' -skip qtactiveqt'
	#		' -skip qtdeclarative'
	#		' -skip qttools'
	#		' -release'
	#		' -accessibility'
	#		' -opengl desktop'
	#		' -no-openssl'
	#		#' -xplatform win32-g++'
	#		' -xplatform mingw-w64-g++'
	#		' -optimized-qmake'
	#		' -verbose'
	#		' -opensource'
	#		' -confirm-license'
	#		' -force-pkg-config'
	#		' -force-debug-info'
	#		' -system-zlib'
	#		' -system-libpng'
	#		' -system-libjpeg'
	#		#' -system-sqlite'
	#		#' -system-freetype'
	#		' -system-harfbuzz'
	#		' -no-direct2d'
	#		' -system-pcre'
	#		' -no-fontconfig'
	#		#' -sql-mysql'
	#		#' -sql-psql'
	#		#' -sql-sqlite'
	#		#' -dbus-linked'
	#		' -no-glib'
	#		' -no-icu'
	#		#' -iconv'
	#		' -nomake examples'
	#		' -make tools'
	#		' -hostprefix {target_sub_prefix}'
	#		' -hostdatadir {target_sub_prefix}/lib/qt'
	#		' -hostbindir {target_sub_prefix}/bin'
	#		' -prefix {target_sub_prefix}'
	#		' -bindir {target_sub_prefix}/bin'
	#		' -archdatadir {target_sub_prefix}/lib/qt'
	#		' -datadir {target_sub_prefix}/share/qt'
	#		' -docdir {target_sub_prefix}/share/doc/qt'
	#		' -examplesdir {target_sub_prefix}/share/qt/examples'
	#		' -headerdir {target_sub_prefix}/include/qt'
	#		' -libdir {target_sub_prefix}/lib'
	#		' -plugindir {target_sub_prefix}/lib/qt/plugins'
	#		' -sysconfdir {target_sub_prefix}/etc'
	#		' -translationdir {target_sub_prefix}/share/qt/translations'
	#		' -device-option CROSS_COMPILE={cross_prefix_bare}'
	#		' -device-option CROSS_target_prefix={target_sub_prefix}'
	#		' -device-option CROSS_COMPILE_CFLAGS=-fpch-preprocess'
	#		' -device-option CUSTOM_LIB_DIR={target_sub_prefix}/lib'
	#		' -device-option CUSTOM_INC_DIR={target_sub_prefix}/include'
	#	,
	#	'depends_on' : [ 'libwebp', 'freetype', 'libpng', 'libjpeg-turbo', 'pcre2', 'd-bus', ],
    #
	#	'patches' : [
	#	],
	#	'_info' : { 'version' : '5.10.1', 'fancy_name' : 'QT5' },
	#},
	#'icu4c' : {
	#	'repo_type' : 'archive',
	#	# 'patches' : [
	#		# ('https://raw.githubusercontent.com/Alexpux/MINGW-packages/master/mingw-w64-icu/0012-libprefix.mingw.patch','-p1')
	#	# ],
	#	'url' : 'http://download.icu-project.org/files/icu4c/60.2/icu4c-60_2-src.tgz',
	#	'rename_folder': 'icu_60_1',
	#	'folder_name' : 'icu',
	#	'source_subfolder' : 'source',
	#	'configure_options': ' --host={target_host} --target={target_host} --prefix={target_prefix} --disable-shared --enable-static --with-cross-build=/xc/gcct/icu_native/source --with-data-packaging=library',
	#	'depends_on' : [ 'zlib', ],
	#	'_info' : { 'version' : '60_2', 'fancy_name' : 'icu' },
	#},
	#'pcre' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://ftp.pcre.org/pub/pcre/pcre-8.41.tar.gz',
	#	'configure_options' : '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --enable-unicode-properties --enable-jit --enable-pcre16 --enable-pcre32 --enable-pcregrep-libz --enable-pcregrep-libbz2',
	#	'depends_on' : [
	#		'bzip2',
	#	],
	#	'_info' : { 'version' : '8.41', 'fancy_name' : 'pcre' },
	#},
	#'d-bus' : {
	#	'repo_type' : 'archive',
	#	'download_locations' : [
	#		{ "url" : "https://dbus.freedesktop.org/releases/dbus/dbus-1.13.4.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "8a8f0b986ac6214da9707da521bea9f49f09610083c71fdc8eddf8b4c54f384b" }, ], },
	#		{ "url" : "https://fossies.org/linux/misc/dbus-1.13.4.tar.gz", "hashes" : [ { "type" : "sha256", "sum" : "8a8f0b986ac6214da9707da521bea9f49f09610083c71fdc8eddf8b4c54f384b" }, ], },
	#	],
	#	'configure_options' : '--host={target_host} --prefix={target_prefix} --disable-shared --enable-static --with-xml=expat --disable-systemd --disable-tests --disable-Werror --disable-asserts --disable-verbose-mode --disable-xml-docs --disable-doxygen-docs --disable-ducktype-docs',
	#	'_info' : { 'version' : '1.13.4', 'fancy_name' : 'D-bus (Library)' },
	#},
	#'openssl_1_0' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://www.openssl.org/source/openssl-1.0.2n.tar.gz',
	#	'configure_options' : '{bit_name3} --prefix={target_prefix} --cross-compile-prefix={cross_prefix_bare} no-shared no-asm',
	#	'configure_path' : './Configure',
	#	'install_target' : 'install_sw', # we don't need the docs..
	#	'env_exports' : {
	#		'CROSS_COMPILE' : '{cross_prefix_bare}',
	#	},
	#	'_info' : { 'version' : '1.0.2n', 'fancy_name' : 'openssl_1.0' },
	#},
	#'glib2' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://developer.gnome.org/glib/glib-html-2.54.3.tar.gz',
	#	'configure_options' : '--host={target_host} --prefix={target_prefix} --with-pcre=system --with-threads=win32 --disable-fam --disable-shared',
	#	'depends_on' : [ 'pcre2' ],
	#	'patches' : [
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/glib2/0001-Use-CreateFile-on-Win32-to-make-sure-g_unlink-always.patch','-Np1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/glib2/0004-glib-prefer-constructors-over-DllMain.patch'               ,'-Np1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/glib2/0017-GSocket-Fix-race-conditions-on-Win32-if-multiple-thr.patch','-p1' ),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/glib2/0027-no_sys_if_nametoindex.patch'                               ,'-Np1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/glib2/0028-inode_directory.patch'                                     ,'-Np1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/glib2/revert-warn-glib-compile-schemas.patch'                         ,'-Rp1'),
	#		# ('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/glib2/use-pkgconfig-file-for-intl.patch'                              ,'-p0' ),
    #
	#	],
	#	'run_post_patch' : [
	#		'./autogen.sh NOCONFIGURE=1',
	#	],
	#	'_info' : { 'version' : '2.54.3', 'fancy_name' : 'glib2' },
	#},
	#'vapoursynth': { 
	#	'repo_type' : 'git',
	#	'url' : 'https://github.com/vapoursynth/vapoursynth.git',
	#	# 'custom_cflag' : '-O3',
	#	'configure_options' : '--host={target_host} --prefix={target_prefix} --enable-static --enable-core --enable-shared --disable-silent-rules',
	#	'patches' : (
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/vapoursynth-0001-statically-link.patch', '-p1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/vapoursynth-0002-api.patch', '-p1'),
	#		('https://raw.githubusercontent.com/DeadSix27/python_cross_compile_script/master/patches/vapoursynth-0003-windows-header.patch', '-p1'),
	#	),
    #
	#},
	#'libgme_game_music_emu' : {
	#	'repo_type' : 'archive',
	#	'url' : 'https://bitbucket.org/mpyne/game-music-emu/downloads/game-music-emu-0.6.1.tar.bz2', # ffmpeg doesnt like git
	#	'conf_system' : 'cmake',
	#	#'run_post_patch': ( # runs commands post the patch process
	#	#	'sed -i.bak "s|SHARED|STATIC|" gme/CMakeLists.txt',
	#	#),
	#	'configure_options': '. {cmake_prefix_options} -DCMAKE_INSTALL_PREFIX={target_prefix} -DBUILD_SHARED_LIBS=OFF',
	#	'_info' : { 'version' : '0.6.1', 'fancy_name' : 'game-music-emu' },
	#},
}

if __name__ == "__main__": # use this as an example on how to implement this in custom building scripts.
	main = CrossCompileScript(PRODUCTS,DEPENDS,VARIABLES)
	main.commandLineEntrace()
