#!/usr/bin/env bash
# https://betterdev.blog/minimal-safe-bash-script-template/

## to do
## improve logging: 
## https://technotes.adelerhof.eu/bash/logging/
## https://blog.tratif.com/2023/01/09/bash-tips-1-logging-in-shell-scripts/
##
set -Eeuo pipefail
trap cleanup SIGINT SIGTERM ERR EXIT

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)

usage() {
  cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [-h] --user <user> --password <password>  --meter <meter> --past <past> | {--from <YYYY-MM-DD[ HH:MM:SS]> --to <YYYY-MM-DD[ HH:MM:SS]} [--host <host>] [--path <path>] [--out <csv|json|xml>] [-v] 
 e.g.: $(basename "${BASH_SOURCE[0]}") --user myUser --password myPassword --meter 01005e318002.1emh0011802881.sm --past 60
       or
       # publish result to mqtt server:
       $(basename "${BASH_SOURCE[0]}") --user myUser --password myPassword --meter 01005e318002.1emh0011802881.sm --past 15 --out json 2>/dev/null | curl -d @- 'mqtt://mqttserver.mylocaldomain.lan/smgw/mySMGW_1'

$(basename "${BASH_SOURCE[0]}") exports data from a Smartmeter Gateway using the han interface.
Thanks to Thomas Müller <tmueller@ivugmbh.de> for pointing me in the right direction.

Note: "Die Abfrage liefert 1445 Datensätze zurück. Es sind nur 1000 erlaubt. Schränken Sie die Abfrageparameter ein."

Available options:

-h, --help      Print this help and exit.
-v, --verbose   Print script debug info.
--host          IP address of Smartmeter Gateway. Default: 192.168.1.200.
--port          Not yet used. Access with https on port 443 always.
--user          Smartmeter Gateway user.
--password      Smartmeter Gateway password.
--meter         Meter to use
--path          Path for the scripts output. Default ist scripts location.
--from          Export data from YYYY-MM-DD[ HH:MM:SS].
--to            Export data to YYYY-MM-DD[ HH:MM:SS].
--past          Export data in the time range of the <past> minutes. If --past is set, --from and --to are not considered.
--out           Format to print to stdout. One of csv|json|xml. Default: csv
EOF
  exit
}

cleanup() {
  trap - SIGINT SIGTERM ERR EXIT
  # script cleanup here
}

setup_colors() {
  if [[ -t 2 ]] && [[ -z "${NO_COLOR-}" ]] && [[ "${TERM-}" != "dumb" ]]; then
    NOFORMAT='\033[0m' RED='\033[0;31m' GREEN='\033[0;32m' ORANGE='\033[0;33m' BLUE='\033[0;34m' PURPLE='\033[0;35m' CYAN='\033[0;36m' YELLOW='\033[1;33m'
  else
    NOFORMAT='' RED='' GREEN='' ORANGE='' BLUE='' PURPLE='' CYAN='' YELLOW=''
  fi
}

msg() {
  echo >&2 -e "${1-}"
}

die() {
  local msg=$1
  local code=${2-1} # default exit status 1
  msg "$msg"
  exit "$code"
}

parse_params() {
  # default values of variables set from params
  flag=0
  host='192.168.1.200'
  port=443
  path=$script_dir
  out='csv'

  while :; do
    case "${1-}" in
    -h | --help) usage ;;
    -v | --verbose) set -x ;;
    --no-color) NO_COLOR=1 ;;
    -f | --flag) flag=1 ;; # example flag
    --host)
      host="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${host}" ]] && die "\"--host\" may not be empty."
      shift
      ;;
    --port)
      port="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${port}" ]] && die "\"--port\" may not be empty."
      shift
      ;;
    --user)
      user="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${user}" ]] && die "\"--user\" may not be empty."
      shift
      ;;
    --password)
      password="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${password}" ]] && die "\"--password\" may not be empty."
      shift
      ;;
    --meter)
      meter="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${meter}" ]] && die "\"--meter\" may not be empty."
      shift
      ;;      
    --path)
      path="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${path}" ]] && die "\"--path\" may not be empty."
      shift
      ;;
    --from)
      from="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${from}" ]] && die "\"--from\" may not be empty."
      shift
      ;;
    --to)
      to="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${to}" ]] && die "\"--to\" may not be empty."
      shift
      ;;
    --past)
      past="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${past}" ]] && die "\"--past\" may not be empty."
      shift
      ;;
    --out)
      out="${2-}"
      ## Reason for next line: if the last paramter in the command line has no value set, logic will beak without any information.
      [[ -z "${out}" ]] && die "\"--out\" may not be empty."
      shift
      ;;    
    -?*) die "Unknown option: $1" ;;
    *) break ;;
    esac
    shift
  done

  #args=("$@")

  # check required params and arguments

  [[ -z "${host-}" ]]      && die "Missing required parameter: host"
  [[ -z "${port-}" ]]      && die "Missing required parameter: port"
  [[ -z "${user-}" ]]      && die "Missing required parameter: user"
  [[ -z "${password-}" ]]  && die "Missing required parameter: password"
  [[ -z "${meter-}" ]]     && die "Missing required parameter: meter"
  [[ -z "${path-}" ]]      && die "Missing required parameter: path"
  [[ -z "${out}" ]]        && die "\"out\" may not be empty"
  if [[ -z "${past-}" ]] 
  then
    [[ -z "${from-}" ]]   && die "Missing required parameter: from"
    [[ -z "${to-}" ]]     && die "Missing required parameter: to"
  fi
  #[[ ${#args[@]} -eq 0 ]] && die "Missing script arguments"

  return 0
}

parse_params "$@"
setup_colors

# script logic here

#https://curl.se/mail/archive-2022-04/0027.html
tcp_port_is_open() {

  # see https://everything.curl.dev/usingcurl/returns
  # relevant here:

  #  6 - Couldn't resolve host.
  #  7 - Failed to connect to host. curl managed to get an IP address to the machine and it tried to setup a TCP connection to the host but failed. This can be because you have specified the wrong port number, entered the wrong host name, the wrong protocol or perhaps because there is a firewall or another network equipment in between that blocks the traffic from getting through.
  # 28 - Operation timeout.
  # 49 - connected to host on port. I.e. OK in this scenario. (Malformed telnet option. The telnet options you provide to curl was not using the correct syntax.)

   local exit_status_code
   curl -t '' --connect-timeout 2 -s telnet://"$1:$2" </dev/null
   exit_status_code=$?
   echo "$exit_status_code"
}

get_OS() {
  # https://stackoverflow.com/questions/3466166/how-to-check-if-running-in-cygwin-mac-or-linux
  
  case "$(uname -sr)" in
    Darwin*)
      OS='Mac OS X'
      ;;

    Linux*Microsoft*)
      OS='WSL'  # Windows Subsystem for Linux
      ;;

    Linux*)
      OS='Linux'
      ;;

    CYGWIN*|MINGW*|MINGW32*|MSYS*)
      OS='MS Windows'
      ;;

    # Add here more strings to compare
    # See correspondence table at the bottom of this answer

    *)
      OS='Other OS' 
      ;;
  esac

  echo "$OS"
}

validate_date() {
  str_length=${#1}

  case $str_length in
    10)
      local RETVAL=0
      ;;

    19)
      local RETVAL=0
      ;;

    *)
      local RETVAL=1
      ;;
  esac

  if [[ $RETVAL -eq 0 ]]
  then
    local tmstmp=$(timestamp_from_string "$1")
  else
    local tmstmp="Error"
  fi

  local  __resultvar=$2
  eval $__resultvar="'$tmstmp'"
}

timestamp_from_string() {
  local date_candiate="$1"
  local str_length="${#date_candiate}"
  local timestamp=0

  local OS=$(get_OS)
  case $OS in
    'Mac OS X')
      if [[ $str_length -eq 10 ]]
      then
        local timestamp=$(date -jf "%Y-%m-%d" "$date_candiate" +%s 2>/dev/null || echo "Error" )
      else
        local timestamp=$(date -jf "%Y-%m-%d %H:%M:%S" "$date_candiate" +%s 2>/dev/null || echo "Error" )
      fi
      ;;

    *)
      local timestamp=$(date --date="$date_candiate" +"%s")
      ;;
  esac

  echo $timestamp
}


string_from_timestamp() {
  local OS=$(get_OS)
  case $OS in
    'Mac OS X')
      local date_string=$(date -r "$1" +"%Y-%m-%d %H:%M:%S")
      ;;

    *)
      local date_string=$(date -d "@$1" '+%Y-%m-%d %H:%M:%S')
      ;;
  esac

  local  __resultvar=$2
  eval $__resultvar="'$date_string'"
}

### check availability of dependencies
CMDS=("curl" "date" "tr" "sed" "awk" "grep" "xmllint" "jq")
for CMD in "${CMDS[@]}"
do
  if ! command -v "$CMD" &> /dev/null
  then
      die "Missing command: $CMD. Please install $CMD."
  fi
done

### check for existence of path
[[ ! -d "$path" ]] && die "path $path does not exist. Enter a valid path."

### check whether path is writable
[[ ! -w "$path" ]] && die "path $path exists, but is not writable. Enter a writable path."

### add trailing slash (/) to path if not exists
path=$(sed 's![^/]$!&/!' <<< $path)
# directory for logging
LOG_PATH="${path}log/"
mkdir -p "${LOG_PATH}"
# directory for data
DATA_PATH="${path}data/"
mkdir -p "${DATA_PATH}"


### check whether $ out is valid
out=$(tr '[:upper:]' '[:lower:]' <<< $out)
case $out in
  'csv'|'json'|'xml')
    ;;

  *)
    die "Requested output format \"$out\" is not valid. Options are one of \"csv\", \"json\" or \"xml\". Default is \"csv\"."
    ;;
esac

### we need to do some logging ...
SCRIPT_NAME=$(basename "${BASH_SOURCE[0]}")
LOG="${LOG_PATH}${SCRIPT_NAME%.*}".log
RESET_LOG=0

function log() {
  datestring=$(date +"%Y-%m-%d %H:%M:%S")
  if (( $RESET_LOG == 0 ))
  then
    RESET_LOG=1
    echo -e "$datestring - $@" > $LOG
  else
    echo -e "$datestring - $@" >> $LOG
  fi
}

### check for connection to host on port
CONN=$(tcp_port_is_open $host $port)
[[ "$CONN" -ne 49 ]] && die "Could not connect to host $host on port $port. curl exited with ststus code $CONN. See https://everything.curl.dev/usingcurl/returns for details."

log "CONN: $CONN (see https://everything.curl.dev/usingcurl/returns)"

### check valid from and to. if past is given, from and to are not considered.
NOW=$(date +"%Y-%m-%d %H:%M:%S")
TIMESTAMP_NOW=0
validate_date "$NOW" TIMESTAMP_NOW

if [[ -z "${past-}" ]] 
then
  # echo "past not given"
  TIMESTAMP_FROM=0
  validate_date "$from" TIMESTAMP_FROM
  if [[ $TIMESTAMP_FROM == "Error" ]]
  then
    die "from ( $from ) is not a valid date. It needs to be \"YYYY-MM-DD[ HH:MM:SS]\" and after 1970. E.g. \"2023-12-31\" or \"2023-12-31 23:59:30\"."
  fi

  TIMESTAMP_TO=0
  validate_date "$to" TIMESTAMP_TO
  if [[ $TIMESTAMP_TO == "Error" ]]
  then
    die "to ( $to ) is not a valid date. It needs to be \"YYYY-MM-DD[ HH:MM:SS]\" and after 1970. E.g. \"2023-12-31\" or \"2023-12-31 23:59:30\"."
  fi

  [[ $TIMESTAMP_TO -le $TIMESTAMP_FROM ]]  && die "from ($from) needs to be before to ($to)."

  NOW=$(date +"%Y-%m-%d %H:%M:%S")
  TIMESTAMP_NOW=0
  validate_date "$NOW" TIMESTAMP_NOW
  [[ $TIMESTAMP_NOW -le $TIMESTAMP_FROM ]] && die "from ($from) needs to be before now ($NOW)."
else  
  ### check whether past is positive integer
  # https://stackoverflow.com/questions/806906/how-do-i-test-if-a-variable-is-a-number-in-bash#:~:text=Bash%20does%20provide%20a%20reliable,0'%20is%20not%20an%20integer.
  re='^[+-]?[0-9]+([0-9]+)?$'
  if ! [[ $past =~ $re ]] ; then
    die "past ($past) is not an integer. It needs to be positive integer gt 0."
  fi
  [[ ! "$past" -gt 0 ]] && die "past ($past) needs to be positive integer gt 0."

  TIMESTAMP_FROM=$(( TIMESTAMP_NOW - ( $past * 60 ) ))
  from=0
  string_from_timestamp "$TIMESTAMP_FROM" from
  to=$NOW
fi

ESCAPED_FROM=$(sed 's/:/_/g; s/ /__/g' <<< $from)
ESCAPED_TO=$(sed 's/:/_/g; s/ /__/g' <<< $to)
RESULT_BASENAME="export_${ESCAPED_FROM}---${ESCAPED_TO}"


### parameter checks done, preparations done.
### now start with real stuff

# At least on MAC OS we need to set an USER AGENT explicitly. Otherwise the result of the request will be incomplete.
# When curl is executed from the command line, the UA does not need to be explicitly specified.
USER_AGENT="curl/7.88.1"

# <form id="form_meterform" name="input" action="/cgi-bin/hanservice.cgi" method="post">
#     <input type="hidden" name="tkn" value="d33858903b17e5d787cfa0921de1678f6c8c55aa2477126de4336026e09fe790">
#     <input type="hidden" name="action" value="meterprofile">Zähler 
#     <select name="mid" id="meterform_select_meter" size="1" onchange="this.form.submit();">
#         <option value="52dc9d18adad336dd8ef97d7b9143a31">01005e318002.1itr0310077721.sm</option>
#         <option value="41f3a8ed992e8ee9da39a3084a387ac3" selected="">01005e318002.1emh0011802881.sm</option>
#     </select>&nbsp;
#     <input type="button" id="form_meterform_button_zaehlerprofil" value="Zählerprofil" onclick="document.forms['input'].elements['action'].value='showMeterProfile'; document.forms['input'].target='_self'; this.form.submit();">&nbsp;
#     <input type="button" id="form_meterform_button_zaehlerstand" value="Zählerstand" onclick="document.forms['input'].elements['action'].value='showMeterValuesForm'; document.forms['input'].target='_self'; this.form.submit();"><hr>
# </form>



HEADER="Content-Type: application/x-www-form-urlencoded"
REQUEST_meterform="action=meterform"

HTML_meterform=$(curl --connect-timeout 10 --digest -u $user:$password --insecure --cookie-jar "${path}cookie-jar.txt" -A "$USER_AGENT" -d "$REQUEST_meterform" -H "$HEADER" -X POST "https://${host}/cgi-bin/hanservice.cgi")
log "HTML_meterform"
log "$HTML_meterform"
log ""

MID=$(xmllint --nowarning --html --xpath "string(//form[@id='form_meterform']//select[@name='mid']/option[contains(text(), '"$meter"')]/@value)" - <<< "$HTML_meterform" 2>/dev/null)
#MID=$(xmllint --nowarning --html --xpath "string(//form[@id='form_meterform']//select[@name='mid']/option[contains(text(), '01005e318002.1emh0011802881.sm')]/@value)" - <<< "$HTML_meterform" 2>/dev/null)
[[ -z "${MID}" ]] && die "MID is empty. Got incomplete HTML? Wrong credentials? See $LOG for more information."
log "MID: $MID"
log ""

TKN=$(xmllint --nowarning --html --xpath "string(//form[@id='form_meterform']//input[@name='tkn']/@value)" - <<< "$HTML_meterform" 2>/dev/null)
[[ -z "${TKN}" ]] && die "TKN is empty. Got incomplete HTML? See $LOG for more information."
log "TKN: $TKN"
log ""

REQUEST_showMeterValuesForm="action=showMeterValuesForm&mid=${MID}&tkn=${TKN}"
log "REQUEST_showMeterValuesForm: $REQUEST_showMeterValuesForm"
log ""

REQUEST_meterprofile="action=meterprofile&mid=${MID}&tkn=${TKN}"
log "REQUEST_meterprofile: $REQUEST_meterprofile"
log ""


HTML_meterprofile=$(curl --connect-timeout 10 --digest -u $user:$password --insecure -A "$USER_AGENT" -d "$REQUEST_meterprofile" -H "$HEADER" -X POST https://${host}/cgi-bin/hanservice.cgi --cookie "${path}cookie-jar.txt")

REQUEST_showMeterValuesForm="action=showMeterValuesForm&mid=${MID}&tkn=${TKN}"
log "REQUEST_showMeterValuesForm: $REQUEST_showMeterValuesForm"
log ""

HTML_showMeterValuesForm=$(curl --connect-timeout 10 --digest -u $user:$password --insecure -A "$USER_AGENT" -d "$REQUEST_showMeterValuesForm" -H "$HEADER" -X POST https://${host}/cgi-bin/hanservice.cgi --cookie "${path}cookie-jar.txt")
log "HTML_showMeterValuesForm: $HTML_showMeterValuesForm"
log ""

MID=$(xmllint --nowarning --html --xpath "string(//form[@name='input_metervalues']//input[@name='mid']/@value)" - <<< "$HTML_showMeterValuesForm" 2>/dev/null)
[[ -z "${MID}" ]] && die "MID is empty. Got incomplete HTML? Wrong credentials? See $LOG for more information."
log "MID: $MID"
log ""

REQUEST_showMeterValues="action=showMeterValues&mid=${MID}&tkn=${TKN}&from=${from}&to=${to}"
log "REQUEST_showMeterValues: $REQUEST_showMeterValues"
log ""

REQUEST_exportMeterValues="action=exportMeterValues&mid=${MID}&tkn=${TKN}&from=${from}&to=${to}"
log "REQUEST_exportMeterValues: $REQUEST_exportMeterValues"
log ""


SIGNED_XML=$(curl --connect-timeout 10 --digest -u $user:$password --insecure -A "$USER_AGENT" -d "$REQUEST_exportMeterValues" -H "$HEADER" -X POST https://${host}/cgi-bin/hanservice.cgi --cookie "${path}cookie-jar.txt" -o "${DATA_PATH}${RESULT_BASENAME}.cms")
# curl does not send to stdout because option -o (send to file) is used
# echo "SIGNED_XML:" >> $LOG
# echo "$SIGNED_XML" >> $LOG
# echo "" >> $LOG

if [[ ! -f "${DATA_PATH}${RESULT_BASENAME}.cms" ]]
then
  die "Something went wrong. File ${DATA_PATH}${RESULT_BASENAME}.cms should exist, but does not."
fi

##
# to handle:
##
# ++ xmllint - --format
# -:1: parser error : Document is empty

# reason:
# "${DATA_PATH}${RESULT_BASENAME}.cms" contained
# Die Abfrage liefert 1445 Datens&auml;tze zur&uuml;ck. Es sind nur 1000 erlaubt. Schr&auml;nken Sie die Abfrageparameter ein.
##
# or
# ++ xmllint - --format
# ++ grep -o '<?xml.*</ns1:object>'
# -:1: parser error : Document is empty
# reason:
# "${DATA_PATH}${RESULT_BASENAME}.cms" contained
# Die Abfrage liefert 1445 Datens&auml;tze zur&uuml;ck. Es sind nur 1000 erlaubt. Schr&auml;nken Sie die Abfrageparameter ein.
# Keine Daten vorhanden.
#
# I.e. the result of the curl request is not always xml. In case of an error, it is a text message.
#
# Note: It takes about two min for 400 records and the maximum of retrieved records may not exceed 1000.

# tr removes non ascii chars and in addition \r and \n (chars are specified as octal). Without linebreaks it is easier to grep for the xml.
# first check whether the result contains xml
[[ -z $( LC_ALL=C tr -cd '11\40-\176' < "${DATA_PATH}${RESULT_BASENAME}.cms" | grep -o '<?xml.*</ns1:object>') ]] && die "Did not get meter values  but \"$(cat "${DATA_PATH}${RESULT_BASENAME}.cms")\"."

# not very smart to do this twice, but it is fast...
# In our scenario it is not possible to assign the result of the "grep" to a variable and test the variable,
# because the assignment of an empty grep result to a variable throws an error and the process dies withou any message.
# That is the reason for doing the grep twice.
XML=$( LC_ALL=C tr -cd '11\40-\176' < "${DATA_PATH}${RESULT_BASENAME}.cms" | grep -o '<?xml.*</ns1:object>' | xmllint - --format)
echo "$XML" > ${DATA_PATH}${RESULT_BASENAME}.xml

CSV="id;value;scaler;unit;status;capture_time"
NODE_COUNT=$(xmllint --xpath 'count(//*[local-name()="entry_gateway_signed"])' - <<< "$XML")
for i in $(seq 1 $NODE_COUNT);do
    line=$(xmllint --xpath "concat(\
       string((//*[local-name()='entry_gateway_signed'])[$i]/@id) , ';', \
       (//*[local-name()='entry_gateway_signed']/*[local-name()='value']/*[local-name()='long64'])[$i]/text() , ';', \
       (//*[local-name()='entry_gateway_signed']/*[local-name()='scaler'])[$i]/text() , ';', \
       (//*[local-name()='entry_gateway_signed']/*[local-name()='unit'])[$i]/text() , ';', \
       (//*[local-name()='entry_gateway_signed']/*[local-name()='status']/*[local-name()='unsigned'])[$i]/text() , ';', \
       (//*[local-name()='entry_gateway_signed']/*[local-name()='capture_time'])[$i]/text() \
     )" - <<< "$XML")
     CSV="${CSV}"$'\n'"$line"
done

echo "$CSV" > ${DATA_PATH}${RESULT_BASENAME}.csv

COUNT=$(xmllint - --xpath 'string(//*[local-name()="column"]/@count)' <<< "$XML")
ID=$(xmllint --xpath 'string(/*[local-name()="object"]/@id)' - <<< "$XML")

JSON=$(jq --arg count "$COUNT" --arg id "$ID" --slurp --raw-input \
    '{id:$id,count:$count, simple_data: ([split("\n") | .[1:] | map(split(";")) |
        map({"id": .[0],
             "value": .[1] ,
             "scaler": .[2] ,
             "unit": .[3] ,
             "status": .[4] ,
             "capture_time": .[5]}) | del(
    .[] 
  | select(.capture_time == null)     
) ] | add)}' <<< "$CSV")

echo "$JSON" > ${DATA_PATH}${RESULT_BASENAME}.json

case $out in
  'csv')
    echo "$CSV"
  ;;

  'json')
    echo "$JSON"
  ;; 

  'xml')
    echo "$XML"
  ;;    
esac

