#!/usr/bin/env python
# -*- coding: utf-8 -*-
##########
#Replacement for Spacebot to write the SpaceAPI entry
#Large chunks of the doorsense code blatantly ripped from irccat.py by Bart Thate.
##########

## jsb imports

from jsb.lib.threads import start_new_thread
from jsb.lib.persist import PlugPersist
from jsb.lib.fleet import getfleet
from jsb.lib.commands import cmnds
from jsb.lib.examples import examples
from jsb.lib.callbacks import callbacks
from jsb.lib.threadloop import ThreadLoop

from jsb.plugs.common.topic import checktopicmode
from jsb.plugs.socket.mpd import mpd

from lights import lightprofile_activate
from wol import on_openspace

## basic imports

import json
import logging
import time
import os
import socket
import SocketServer
from SocketServer import ThreadingMixIn, StreamRequestHandler

## defines

testing = False

ACCEPTABLEUNITS = [u'\N{DEGREE SIGN}C',u'\N{DEGREE SIGN}F', 'K' ,u'\N{DEGREE SIGN}De',
                   u'\N{DEGREE SIGN}N',u'\N{DEGREE SIGN}R',u'\N{DEGREE SIGN}R\N{LATIN SMALL LETTER E WITH ACUTE}',
                   u'\N{DEGREE SIGN}R\N{LATIN SMALL LETTER O WITH STROKE}']

tcppassword = PlugPersist('tcppassword')

APIFILE = '/mnt/spaceapi/status.json'

cfg = PlugPersist("doorsense")

sensorlist = PlugPersist('sensorlist', {
#sensorlist.data = {
    'door_locked':[
        {'value':None,'location':'front_door','name':"front_door",'description':""},
        {'value':None,'location':'back_door','name':"back_door",'description':""}
    ],
    'temperature':[],
    'barometer':[],
    'humidity':[],
    'beverage_supply':[],
    'power_consumption':[],
    'wind':[],
    'network_connections':[],
    'account_balance':[],
    'total_member_count':[],
    'people_now_present':[]
#radiation   #This is a super complex one. :/

})
sensorlist.save()

statussensors = PlugPersist('statussensors')
statussensors.save()

currentstatus = PlugPersist('currentstatus', False)

shared_data = {}
server = None
graphite = None
outputthread = None

## dummy callbacks to make sure plugin gets loaded on startup
def dummycb(bot, event): pass
callbacks.add("START", dummycb)

#def apiEvents():
#    return []

def statusStr(openstatus):
    if openstatus: return 'Open' 
    else: return 'Closed'

def doorStr(status):
    if str(status).lower()=='true': return 'Locked'
    elif str(status).lower()=='false': return 'Unlocked'
    else: return 'Unknown'

def apiupdate(openStatus=None, who="unknown"):
    if openStatus is None:
        if str(currentstatus.data).lower()=='true': openStatus = True #Hackish fix!
        else: openStatus = False
    outputsensors={}
    for type in sensorlist.data:
        if len(sensorlist.data[type])>0:
            outputsensors[type]=sensorlist.data[type]
    api13 = {"api":"0.13","space":"NURDSpace",
    "logo":"http://nurdspace.nl/spaceapi/logo.png",
    "url":"http://nurdspace.nl/",
        "location":{
        "address":"Churchillweg 68, 6706 AD Wageningen, The Netherlands",
        "lat":51.973276,
        "lon":5.672886},
        "spacefed":{
        "spacenet":True,
        "spacesaml":True,
        "spacephone":False},
    "cam":["http://space.nurdspace.nl/video/channel_0.gif"],
    "state":{
        "open":bool(openStatus),
        "lastchange":int(time.time()),
        "trigger_person":who, #Yeah, I know. This is a FIXME
        "message":"Space is "+statusStr(currentstatus.data).upper(),
        "icon":{"open":"http://nurdspace.nl/spaceapi/icon-open.png",
        "closed":"http://nurdspace.nl/spaceapi/icon-closed.png"} },
#    "events":apiEvents(),
    "issue_report_channels":["ml"],
    "contact":{"irc":"irc://irc.oftc.net/#nurds",
        "twitter":"@NURDspace",
        "ml":"nurds@nurdspace.nl"},
    "sensors":outputsensors,
#    "feeds":"",
#    "projects":"",
    "cache":{"schedule":"m.02"}
    }

    tmpapifilename ='/mnt/spaceapi/status.json.tmp'
    apifilename ='/mnt/spaceapi/status.json'
    try:
        with open(tmpapifilename,'w') as apifile:
            json.dump(api13, apifile,indent=1)
            apifile.flush()   # Build atomic operation to prevent zero-length files
            os.fsync(apifile.fileno()) 
        os.rename(tmpapifilename, apifilename)
    except:
        logging.error('write failed on status.json.')

def spaceapi_graphite(sensortype, sensor, value):
    global graphite
    if not graphite:
        graphite = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        graphite.connect(('graphite.nurdspace.lan',2003))
    value = str(value)
    if value.lower() == 'true': value = '1'
    if value.lower() == 'false': value = '0'
    try:
        message = 'sensors.spaceapi.'+sensortype+'.'+sensor+' '+value+' '+str(int(time.time()))
        graphite.sendall(message+'\n')
        logging.debug('Sent: '+ message)
    except:
        logging.warn('Graphite transmission failure.')

def doorsense_output(msg):
    '''The listener code for the sensor server.'''
    pswd = tcppassword.data['password']
    if msg[:len(pswd)] == pswd:
        msg = msg[len(pswd):]
        recvsensors = []
        try:
            for part in msg.split(';'):
                rsensor,rvalue = tuple(part.split(':')) #unpack to expose errors
                recvsensors.append((rsensor,rvalue))
        except: 
            logging.error('Recieved incorrectly formatted message.')
            return
        fleet = getfleet()
        for rsensor,rvalue in recvsensors:
            for type in sensorlist.data:
                for n, sensor in enumerate(sensorlist.data[type]):
                    if rsensor.lower() == sensor['name'].lower():
                        try:
                            if type == 'door_locked': 
                                if rvalue.lower() == 'true': sensor['value']=True
                                elif rvalue.lower() == 'false': sensor['value']=False
                                else: sensor['value']=None
                                for botname in fleet.list():
                                    bot = fleet.byname(botname)
                                    if bot:
                                        bot.say('#nurds',str(rsensor)+' is '+doorStr(rvalue))
                                statuscheck()
                            else:
                                sensor['value']=float(rvalue)
                                if testing:
                                    for botname in fleet.list():
                                        bot = fleet.byname(botname)
                                        if bot:
                                            bot.say('#nurdbottest',str(rsensor)+' is '+str(rvalue))
                        except Exception, e:
                            logging.error('Something failed when setting sensors: %s'%e)
                        sensorlist.data[type][n] = sensor
                    spaceapi_graphite(type,sensor['name'].lower(),sensor['value'])
        sensorlist.save()
        apiupdate()

## doorsenseOutputThread

class doorsenseOutputThread(ThreadLoop):

    def handle(self, msg):
        doorsense_output(msg)

## doorsenseListener class

class doorsenseListener(ThreadingMixIn, StreamRequestHandler):

    def handle(self):
        msg = self.rfile.readline().strip()
        logging.warn("received %s" % msg)
        if outputthread and msg: outputthread.put(5, msg)        



## plugin initialisation

def init_threaded():
    global server
    global outputthread
    if server: logging.warn("doorsense server is already running.") ; return
    if not cfg.data.enable: logging.warn("doorsense is not enabled.") ; return 
    time.sleep(3)
    if "host" not in cfg.data or "port" not in cfg.data:
        cfg.data["host"] = ""
        cfg.data["port"] = 55555
        cfg.data["botnames"] = ["default-sxmpp",]
        tcppassword.data['password']='777'
        tcppassword.save()
        cfg.save()
    try:
        server = SocketServer.TCPServer((cfg.data["host"], int(cfg.data["port"])), doorsenseListener)
    except Exception, ex: logging.error(str(ex)) ; return
    logging.warn("starting doorsense server on %s:%s" % (cfg.data["host"], cfg.data["port"]))
    start_new_thread(server.serve_forever, ())
    outputthread = doorsenseOutputThread()
    outputthread.start()

def shutdown():
    global server
    if server:
        logging.warn("shutting down the doorsense server")
        server.shutdown()
    if graphite:
        logging.warn("shutting down the graphite conection")
        graphite.close()
    if outputthread: outputthread.stop()


def statuscheck():
    teststatus = False
    for door in sensorlist.data['door_locked']:
        if door['name'] in statussensors.data:
            if door['value'] != statussensors.data[door['name']]:
                teststatus=True
    if teststatus is not currentstatus.data:
        currentstatus.data = teststatus
        currentstatus.save()
        fleet = getfleet()
        for botname in fleet.list():
            bot = fleet.byname(botname)
            if bot:
                if not testing: bot.say('#nurds','Space status is now '+statusStr(teststatus))
                bot.say('#nurdbottest','Space status is now '+statusStr(teststatus))
        if not testing: lightset(teststatus)
        if not testing: topicset(teststatus) #was start_new_thread() but removed for threadleaking
        if not testing: wol_trigger(teststatus)
        if not testing: mpdset(teststatus)
        if not testing: apiupdate()

def topicset(state):
    retval = None
    try:
        fleet = getfleet()
        for botname in fleet.list():
             bot = fleet.byname(botname)
             if bot:
                 topicdata = bot.gettopic('#nurds')
        splitted = topicdata[0].split(' | ')
        statusline = splitted[0]
        if 'Space is ' in statusline:
            del splitted[0]
        if state:
            splitted.insert(0,'Space is OPEN')
            retval = True
        else:
            splitted.insert(0,'Space is CLOSED')
            retval = False
        newtopic = ' | '.join(splitted)
        for botname in fleet.list():
            bot = fleet.byname(botname)
            if bot and newtopic != topicdata[0]:
                if not testing: bot.settopic('#nurds', newtopic)
#            if testing: bot.settopic('#nurdbottest', newtopic)
    except:
        pass
    return retval

def mpdset(state):
    mpdstats = mpd('status') #list of tuples
    for x, y in mpdstats:
        if x == 'state': mpdstate = y
    if state:
        if mpdstate == 'pause': mpd('play')
    else:
        if mpdstate == 'play': mpd('pause')

def lightset(state):
    if state:
        lightprofile_activate('on')
    else:
        lightprofile_activate('off')

def wol_trigger(state):
    if state:
        on_openspace()

def handle_status(bot, ievent):
    cs = currentstatus.data
    ievent.reply('Space is currently '+statusStr(cs)+'.')
    sensorstr = ''
    for type in sensorlist.data:
        if len(sensorlist.data[type])>0:
            sensorstr = sensorstr + str(type)+': '
            for sensor in sensorlist.data[type]:
                sensorstr = sensorstr + str(sensor['name'])+'='+str(sensor['value'])+' '
    ievent.reply('Sensors: '+sensorstr)
    topicset(cs) #Occasionally needed to fix topic

cmnds.add('status', handle_status, 'USER', threaded=True)
examples.add('status', 'Gets the space status and sensor info', 'status')

def handle_addsensor(bot, ievent):
    """ arguments: <sensor type> <JSON>  - add a new sensor for the sensor listener. """
    try: sensortype = ievent.args[0].lower() ; jsoncode = unicode(' '.join(ievent.args[1:]))
    except IndexError: ievent.missing('<sensor type> <JSON-formatted string from http://spaceapi.net/documentation>') ; return
    if not jsoncode: ievent.missing('<sensor type> <JSON-formatted string from http://spaceapi.net/documentation>') ; return
    try:
        logging.warn("attempting to add to "+sensortype+": "+jsoncode)
        pycode = json.loads(jsoncode)
    except:
        ievent.reply('Incorrect JSON string.') ; return
    try:
        name = pycode['name'].lower()
        pycode['name']=name
    except: ievent.reply('missing "name" in JSON') ; return
    try: location = pycode['location']
    except: ievent.reply('missing "location" in JSON') ; return
    try: value = pycode['value'].lower()
    except: pycode['value']=None
    try:
        unit = pycode['unit']
        if sensortype == 'temperature': 
            if unit not in ACCEPTABLEUNITS: raise Exception
    except:
        ievent.reply('Missing appropriate unit in JSON. Appropriate units are: '+unicode(ACCEPTABLEUNITS))
        return
    try:
        sensorlist.data[sensortype].append(pycode)
        sensorlist.save()
    except:
        ievent.reply('Incorrect sensor type.') ; return
    ievent.reply(name+' added to '+sensortype)
    return

def handle_delsensor(bot, ievent):
    """ arguments: <sensor type> <sensor name> Delete a sensor."""
    try: sensortype = ievent.args[0].lower() ; name = ' '.join(ievent.args[1:]).lower()
    except IndexError: ievent.missing('<sensor type> <sensor name>') ; return
    if not name: ievent.missing('<sensor type> <sensor name>') ; return
    try:
        slist = sensorlist.data[sensortype]
    except:
        ievent.reply('Incorrect sensor type.')
    try:
        rlist = []
        removedcount = 0
        for sensor in slist:
            if sensor['name'] != name:
                rlist.append(sensor)
                removedcount = removedcount+1
        if removedcount == 0: raise Exception
        sensorlist.data[sensortype]=rlist
        sensorlist.save()
    except:
        ievent.reply('Sensor name not matched.')
    ievent.reply(name+' removed from '+sensortype)
    return

cmnds.add('sensor-add', handle_addsensor, 'SPACE', threaded=True)
examples.add('sensor-add', 'Add a new sensor for the sensor server', u'sensor-add temperature {"name":"283C01C703000018","value":null,"location":"Inside","description":"","unit":"\N{DEGREE SIGN}C"}')
cmnds.add('sensor-del', handle_delsensor, 'SPACE', threaded=True)
examples.add('sensor-del', 'Delete a sensor from the server', 'sensor-del temperature 283C01C703000018')

def handle_statustoggle(bot, ievent):
    '''Forces the current status to change modes.'''
#    topicdata = bot.gettopic(ievent.channel)
#    if not topicdata: ievent.reply("can't get topic data") ; return
#    splitted = topicdata[0].split(' | ')
#    statusline = splitted[0]
#    if 'Space is ' in statusline:
#        del splitted[0]
#    if statusline == 'Space is OPEN':
    if currentstatus.data == True:
        ievent.reply('Current Status is OPEN. Forcing to CLOSED.')
        currentstatus.data = False
    else:
        ievent.reply('Current Status is CLOSED. Forcing to OPEN.')
        currentstatus.data = True
    currentstatus.save()
    cs = currentstatus.data
    topicset(cs)
    mpdset(cs)
    apiupdate(cs)
    lightset(cs)
    wol_trigger(cs)

cmnds.add('statustoggle', handle_statustoggle, 'SPACE', threaded=True)
examples.add('statustoggle', 'Toggles the space status', 'statustoggle')

def handle_doorsense_enable(bot, event):
    cfg.data.enable = True ; cfg.save() ; event.done()
    init_threaded()
    
cmnds.add("doorsense-enable", handle_doorsense_enable, "OPER")
examples.add("doorsense-enable", "enable doorsense server", "doorsense-enable")

def handle_doorsense_disable(bot, event):
    cfg.data.enable = False ; cfg.save() ; event.done()
    shutdown()

def topiccb(bot, ievent):
    topicset(currentstatus.data)

lastcall = time.time()
def pretopiccb(bot, ievent):
    global lastcall
    if time.time()-10>lastcall:
        lastcall = time.time()
        return True
    else:
        return False

callbacks.add('PRIVMSG', topiccb, pretopiccb)
callbacks.add('JOIN', topiccb, pretopiccb)
callbacks.add('QUIT', topiccb, pretopiccb)
cmnds.add("doorsense-disable", handle_doorsense_disable, "OPER")
examples.add("doorsense-disable", "disable doorsense server", "doorsense-disable")


