#!/bin/sh
#
# Galaxy init script written by Michael Rusch and Peter Li
#

### BEGIN INIT INFO
# Provides:                     galaxy
# Required-Start:               $local_fs $remote_fs $network
# X-UnitedLinux-Should-Start:
# Required-Stop:                $local_fs $remote_fs $network
# X-UnitedLinux-Should-Stop:
# Default-Start:                3 5
# Default-Stop:                 0 1 2 6
# Short-Description:            Galaxy daemon
# Description:                  Start the Galaxy daemon
### END INIT INFO

#For log information, see ./paster.log

GALAXY_RUN="./run.sh"
GALAXY_USER=@user@

if [ ! -f ./config/galaxy.ini ]; then
    echo "File config/galaxy.ini not found!"
fi

if [ ! -f ./config/tool_shed.ini ]; then
    echo "File config/tool_shed.ini not found!"
fi

if [ ! -f ./config/tool_sheds_conf.xml ]; then
    echo "File config/tool_sheds_conf.xml not found!"
fi

case "$1" in
    start)
        echo "Starting galaxy..."
        $GALAXY_RUN --daemon
        rc_done=$rc_done_up
        #Check status
        $GALAXY_RUN --status
        ;;
    stop)
        echo "Stopping galaxy..."
        $GALAXY_RUN --stop-daemon
        ;;
    restart)
        $0 stop
        $0 start
        ;;
    *)
        echo "Usage: $0 start|stop|restart"
        exit 1
esac
