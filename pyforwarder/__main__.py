import sys
import os
import getopt
import json
import yaml
from socket import socket, AF_INET, SOCK_STREAM
import select
import threading

__version__     = '0.10.001'
__author__      = 'Marc Bertens-Nguyen'
__copyright__   = 'equensWorldline se, the Netherlands'

ports = {
    'http': 80,
    'https': 443,
    'imaps': 993,
    'smtps': 587,
    'smtps_old': 465,
}

global verbose
verbose = False

global config
config = {
    'ports': ports,
    'hosts': [
        { 'source':         { 'addr': '0.0.0.0', 'port': 8008 },
          'destination':    { 'addr': 'defmcrvmx007.defm.awl.atosorigin.net', 'port': 'imaps' } },
        { 'source':         { 'addr': '0.0.0.0', 'port': 8009 },
          'destination':    { 'addr': 'defmvmx009.defm.awl.atosorigin.net', 'port': 'smtps' } },
        { 'source':         { 'addr': 'localhost','port': 8010 },
          'destination':    { 'addr': 'sts20029','port': 'http' } },
    ]
}


class Listener( socket ):
    def __init__( self, host, port, destination, listen = 2 ):
        self.__host = host
        self.__port = port
        self.__dest = destination
        socket.__init__( self, AF_INET, SOCK_STREAM )
        self.bind( (host,port) )
        self.listen( listen )
        global verbose
        if verbose:
            print( 'listening on',(host,port) )

        self.setblocking( False )
        return

    @property
    def destination( self ):
        return self.__dest


class Transfer( threading.Thread ):
    def __init__( self, name, connection, destination ):
        self.__active = True
        threading.Thread.__init__( self )
        self.__name = name
        self.__conn = connection
        self.__dest = destination
        self.__destSock = socket( AF_INET, SOCK_STREAM )
        self.__destSock.connect( ( self.__dest[ 'addr' ], self.__dest[ 'port' ] ) )
        self.__destSock.setblocking( 0 )
        self.start()
        return

    @property
    def active( self ):
        return self.__active

    def run( self ):
        global verbose
        try:
            if verbose:
                print( "Starting the transfer: {}".format( self.__name ) )

            inputs = [ self.__conn, self.__destSock ]
            outputs = []
            excepts = [ self.__conn, self.__destSock ]
            while True:
                readable, writable, exceptional = select.select( inputs, outputs, excepts )
                for rd in readable:
                    if rd == self.__conn:
                        data = self.__conn.recv( 4096*5 )
                        if verbose:
                            print( "Receive source {} {}".format( self.__name, len( data ) ) )

                        if len( data ) == 0:    # close
                            self.__destSock.close()
                            break

                        self.__destSock.sendall( data )

                    elif rd == self.__destSock:
                        data = self.__destSock.recv( 4096*5 )
                        if verbose:
                            print( "Receive dest {} {}".format( self.__name, len( data ) ) )

                        if len( data ) == 0:
                            self.__conn.close()
                            break

                        self.__conn.send( data )

                if len( exceptional ) > 0:
                    if verbose:
                        print( "exception on socket: {}".format( self.__name ) )

                    break

        except Exception as exc:
            print( exc, file = sys.stderr )

        if verbose:
            print( "Finished with transfer: {}".format( self.__name ) )

        self.__active = False
        return


def usage():
    print( '''
Syntax:
    forwarder.py [ <options> ] <config-file>
      
Options:
    -v
    -h/--help   This information
      
''' )


def banner():
    l1 = 64 - ( len( __version__ ) + len( __copyright__ ) )
    l2 = 66 - len( __author__ )
    print( """+{line}+
| Forwarder, {vers}, {copy}{fill1}|
| Written by {auth}{fill2}|
+{line}+""".format( vers = __version__, copy = __copyright__, auth = __author__,
                    line = '-' * 78, fill1 = ' ' * l1, fill2 = ' ' * l2 ) )


def main( argv ):
    global config, verbose
    banner()
    try:
        opts, args = getopt.getopt( sys.argv[ 1: ],"hv",[ "help" ] )

    except getopt.GetoptError as err:
        # print help information and exit:
        print( str( err ) ) # will print something like "option -a not recognized"
        usage()
        sys.exit( 2 )

    configFile = None
    for o,a in opts:
        if o == "-v":
            verbose = True

        elif o in ( "-h", "--help" ):
            usage()
            sys.exit()

        else:
            assert False,"unhandled option"

    if len( args ) == 0:
        print( "Missing configuration file" )
        exit(-1)

    configFile = args[ 0 ]
    if os.path.isfile( configFile ):
        if configFile.lower().endswith( ".json" ):
            config = json.load( open( configFile, 'r' ) )

        elif configFile.lower().endswith( ".yaml" ):
            config = yaml.load( open( configFile,'r' ) )

        else:
            print( "Configuration file format is invalid" )
            exit( -3 )

    else:
        print( "Configuration file could not be found" )
        exit( -2 )

    if 'ports' not in config:
        config[ 'ports' ] = ports

    for addr in config[ 'hosts' ]:
        for key in addr:
            if isinstance( addr[ key ][ 'port' ], str ):
                addr[ key ][ 'port' ] = config[ 'ports' ][ addr[ key ][ 'port' ] ]

    if verbose:
        print( json.dumps( config, indent = 4 ) )

    inputs = [  ]
    for addr in config[ 'hosts' ]:
        inputs.append( Listener( addr[ 'source' ][ 'addr' ],
                                 addr[ 'source' ][ 'port' ],
                                 destination = addr[ 'destination' ] ) )

    outputs = []
    excepts = inputs
    transfers = []
    if verbose:
        print( "running the listeners" )

    while inputs:
        readable, writable, exceptional = select.select( inputs, outputs, excepts )
        for rd in readable:
            connection, client_address = rd.accept()
            connection.setblocking( 1 )
            try:
                if verbose:
                    print( "Incomming: {}".format( client_address ) )

                transfers.append( Transfer( "{}:{}".format( *client_address ), connection, rd.destination ) )

            except Exception as exc:
                print( exc, file = sys.stderr )

        for exc in exceptional:
            inputs.remove( exc )

        idx = 0
        while idx < len( transfers ):
            if not transfers[ idx ].active:
                if verbose:
                    print( "cleanup {}".format( transfers[ idx ] ) )

                transfers.remove( transfers[ idx ] )

            else:
                idx += 1

    for tr in transfers:
        if verbose:
            print( "joining {}".format( tr ) )

        tr.join()

    return


main( sys.argv[ 1 : ] )
