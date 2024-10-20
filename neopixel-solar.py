#
#Thanks so much to Uwe Moslehner in the Enphase Users + Owners FB group for the example of Token Auth working on D7 firmware.

# Hot water element size in watts + 300 to avoid on/off cycling.
run_power = 2000         # size of the hot water element + 200 W
grid_draw = 0            # this is the baseline added to solar production to offset a series of poor solar production days
start_hour = 10          # hours post midnight before switching starts, to avoid telegraphing at sun comes up
heating_done = 0         # minutes of relay on with power < element (surrogate marked for themostat off and heating done)
voltage = 240            # set here to solve json float problems

import os
import sys #allows use of sys.exit()
import urequests
import network
from umqtt.simple import MQTTClient
from utime import sleep
from machine import Pin, I2C, RTC
from neopixel import NeoPixel
import json
import random  #for the random start delay
import ntptime
import gc
import secrets


#Make these global to keep pixel status updates easy
solar_production = 0
power_consumption = 0
evse_consumption = 0
shelly_power = 0

#max_freq sets the maximum frequency in Hz and accepts the values 20000000, 40000000, 80000000, 160000000, and 240000000
#machine.freq(160000000)



NUMBER_PIXELS = 25
LED_PIN = 8
strip = NeoPixel(Pin(LED_PIN), NUMBER_PIXELS)

pin_led = Pin(10, mode=Pin.OUT)
pin_led.off()

network.country("AU")
sta_if = network.WLAN(network.STA_IF)
sta_if.active(False) # TOGGLING THIS PREVENTS "OSError: Wifi Internal Error"
sta_if.active(True)
#sta_if.config(pm=sta_if.PM_NONE) # disable power management, seems to need active(TRUE) first
#sta_if.config(pm=sta_if.PM_PERFORMANCE) # disable power management, seems to need active(TRUE) first
sta_if.config(pm=sta_if.PM_POWERSAVE) # disable power management, seems to need active(TRUE) first
loopnum = 0
errcount = 0

################################
def npixel(i,red,green,blue):
#    i = i -6
    if i > 24: i = 24
    strip[i] = (red,green,blue) # red=255, green and blue are 0
    strip.write() # send the data from RAM down the wire
    return


#################################
def do_connect():
  loopnum = 0

  while not sta_if.isconnected():
     loopnum = 0
     try:
         sta_if.active(False)
         sta_if.active(True)
         sta_if.config(txpower=10)
         sta_if.connect(secrets.SSID, secrets.wifi_password)
         print('Maybe connected now: {}...'.format(sta_if.status()))
         sleep(1)
     except:
         print("well that attempt failed")
         sta_if.disconnect()
         sta_if.active(False)

     while loopnum < 25:
         print('Got status {}...'.format(sta_if.status()))
         if sta_if.status() == 2:  #Magenta
             npixel(loopnum,1,0,1)
         elif sta_if.status() == 1001: #Yellow, Connecting
             npixel(loopnum,1,1,0)
         elif sta_if.status() == 202: #Cyan, Password error
             npixel(loopnum,0,1,1)
         elif sta_if.status() == 1000: #Green, Idle/waiting
             npixel(loopnum,0,1,0)
         elif sta_if.status() == 203: #Blue, Association fail
             npixel(loopnum,0,0,1)
         elif sta_if.status() == 1010: #CONNECTED
             npixel(loopnum,1,1,1)
             sleep(1)
             break
         else:
             npixel(loopnum,1,0,0)  #Red, Some other error

         loopnum = loopnum + 1
         sleep(1)

# Never got error 201 No AP, 200 Timeout, 204 Handshake timeout
     if loopnum >= 25:
         loopnum = 0
         strip.fill((0,0,0))  #Clears the neopixels
         strip.write()

  else:
     if sta_if.status() == 1010: #Connected
         if loopnum > 1: npixel(loopnum,1,1,1)
         print("Wifi is connected")
         sleep(1)
     else:
         print('Wifi connection failed: {}...'.format(sta_if.status()))
         npixel(loopnum,1,0,0)
  return


#########################
def syncnettime():
# https://docs.micropython.org/en/latest/library/machine.RTC.html
  gc.collect()
  for loopnum in range(0, 3):
    try:
      npixel(loopnum,0,0,1)
      print("Getting current time from net")
      response = urequests.get("http://worldtimeapi.org/api/timezone/Australia/Brisbane")
      json_data = json.loads(response.text)
      response.close()
      print(json_data)

      current_time = json_data["datetime"]
      the_date, the_time = current_time.split("T")
      year, month, mday = [int(x) for x in the_date.split("-")]
      the_time = the_time.split(".")[0]
      hours, minutes, seconds = [int(x) for x in the_time.split(":")]

      print(year, month, mday, 0, hours, minutes, seconds, 0)

      #sets the date and time from the extracted JSON data
      rtc.datetime((year, month, mday, 0, hours, minutes, seconds, 0))

      t = rtc.datetime()
      timestamp = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(t[0], t[1], t[2], t[4], t[5], t[6])
      print(timestamp)
    except OSError as err:
#      npixel(loopnum,1,0,0)
      print(err)
      print("OSError:", gc.mem_free())
      if err == "-202": do_connect()
      sleep(loopnum * 2)
    except Exception as err:
      print(err)
      sleep(loopnum * 2)
    except:
      print("Something else went wrong, time syncing failed")
      sleep(loopnum * 2)
    else:
      npixel(loopnum,1,1,1)
      print("Time sync complete")
      sleep(1)
      return()
  npixel(loopnum,1,0,0)
  sleep(3)
  import machine
  machine.reset()
  return()

##############################################################################
#def read_production_data(solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage):
def read_production_data():
  rtc = RTC()
  t = rtc.datetime()
  global solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage
  if solar_production > 0: drawpixels('cyan')

  #url = 'http://envoy.local/production.json'
  url = 'https://192.168.1.101/production.json'

    # NOTE: I was getting connect refused when hitting envoy.local, probably due to some router DNS problems, so I set a static IP:
    # Error Connecting: HTTPConnectionPool(host='envoy.local', port=80): Max retries exceeded with url: /production.json (Caused by NewConnectionError('<urequests.packages.urllib3.connection.HTTPConnection object at 0x75cf3ad0>: Failed to establish a new connection: [Errno -2] Name or service not known',))

  solar_today = 0
#  while power_consumption == 0:
  headers = {
  "Accept": "application/json",
  "Authorization": secrets.authtoken,
  }
  try:

      response = urequests.get(url, headers=headers) # self-signed certificate
      json_data = json.loads(response.text)
      response.close()


      solar_production = json_data['production'][1]['wNow']
      voltage = json_data['production'][1]['rmsVoltage']
      solar_today = json_data['production'][1]['whToday']
      power_consumption = json_data['consumption'][0]['wNow']
      consumption_today = json_data['consumption'][0]['whToday']

      solar_today = solar_today / 1000
      consumption_today = consumption_today / 1000


  except:
      t = rtc.datetime()
      timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
      print(timestamp + "Error getting solar reading, now returning")
      global errcount
      errcount = errcount + 1
      #pin_led.on() #use on board LED as error indicator
 
#      timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
#      ev_kw = evse_consumption / 1000
#      ev_kwh = evse_energy / 1000
#      hw_kw = shelly_power / 1000
#      hw_kwh = shelly_temp /1000000
#      display.fill(0)
#      display.text("S:" + "{:.0f}".format(solar_production) + "W  P:" + "{:.0f}".format(power_consumption) + "W", 0, 0, 1)
#      display.text("E:" + "{:.1f}".format(ev_kw) + "kW  " + "{:.1f}".format(ev_kwh) + "kWh", 0, 8, 1)
#      display.text("H:" + "{:.1f}".format(hw_kw) + "kW  " + "{:.1f}".format(hw_kwh) + "kWh", 0, 16, 1)
#      display.text(timestamp + " " + "{:.1f}".format(voltage) + "V", 0, 24, 1)
#      display.show()

      if solar_production > 0: drawpixels('red')
      sleep(1)

#      t = rtc.datetime()
#      timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
      do_connect() #check wifi connected

#      return(solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage)
      return(solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage)


      #  do_connect() #check wifi connected
#  return solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage
  return(solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage)


##############################################
def publish_mqtt(target):
#  strip[0] = (0,1,1) # red=255, green and blue are 0
#  strip.write() # send the data from RAM down the wire

  extra_power = solar_production - (power_consumption - evse_consumption)

  # this sorts out weird spikes in MQTT available power, due to EVSE reporting incorrectly high as it fires up
  if evse_consumption > power_consumption: extra_power = solar_production


  t = rtc.datetime()
  # if evse if off, solar +ve and > evse_start_solar
  if extra_power < evse_min_power and solar_production > evse_start_solar and evse_consumption < 1000 and solar_production > power_consumption-shelly_power and t[4] < 16:
     extra_power = evse_min_power
  # if evse is on, using majority of power and solar > evse_min_solar
  elif extra_power < evse_min_power and evse_consumption > 1000 and evse_consumption/power_consumption > 0.46 and solar_production > evse_min_solar and t[4] < 16:
     extra_power = evse_min_power

#  if extra_power < evse_min_power and evse_consumption > 2200: evse_min_solar = 50

#     print("Setting EVSE to", extra_power, "while available solar is >", evse_min_solar, "and spare solar is not available")

  if target == "csvlog":
    if solar_production > 0: drawpixels('blue')

    t = rtc.datetime()
    timestamp = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(t[0], t[1], t[2], t[4], t[5], t[6])

    mqttstring = timestamp+", "\
            +str("{:.0f}".format(solar_production))+", "\
            +str("{:.0f}".format(power_consumption))+", "\
            +str("{:.0f}".format(shelly_power))+", "\
            +str("{:.1f}".format(shelly_temp))+", "\
            +str("{:.3f}".format(solar_today))+", "\
            +str("{:.3f}".format(consumption_today))+", "\
            +str("{:.1f}".format(voltage))+", "\
            +str("{:.1f}".format(evse_temp))+", "\
            +str("{:.0f}".format(evse_consumption))+", "\
            +str("{:.0f}".format(extra_power))
    mqttdata = mqttstring.encode() #convert to bytearray to send to MQTT
  else:
    mqttdata = "{:.1f}".format(extra_power)

  try:

    client_name = 'ESP32'
    broker_addr = '192.168.1.17'
    mqttc = MQTTClient(client_name, broker_addr, keepalive=60)
    mqttc.connect()

    mqttc.publish(target, mqttdata)
    mqttc.publish("solar/power_consumption","{:.0f}".format(power_consumption))
    mqttc.publish("solar/solar_production","{:.0f}".format(solar_production))
    evse = evse_consumption + shelly_power
    mqttc.publish("solar/evse","{:.0f}".format(evse))
    mqttc.publish("solar/voltage","{:.1f}".format(voltage))
    mqttc.disconnect()


  except:
    if solar_production > 0 and target == "csvlog": drawpixels('red')
    t = rtc.datetime()
    timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
    print("MQTT publishing failed", timestamp)
    if target == "csvlog": do_connect() #check wifi connected

  return()




#################### Gets the OpenEVSE status
def read_evse_data(evse_consumption):
#    strip[0] = (0,0,1) # red=255, green and blue are 0
#    strip.write() # send the data from RAM down the wire

    old_evse_consumption = evse_consumption
    if solar_production > 0: drawpixels('magenta')
    try:

       response = urequests.get('http://192.168.1.102/status', timeout=3)
       json_data = json.loads(response.text)
       response.close()

       evse_energy = json_data['session_energy']
       amp = json_data['amp'] / 1000
       evse_consumption = amp * voltage
       evse_temp = json_data['temp'] / 10
    except:
       evse_energy = -1
       evse_temp = -1
       evse_consumption = old_evse_consumption

       rtc = RTC()
       t = rtc.datetime()
       timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])

       print(timestamp + " Error contacting OpenEVSE")
       if solar_production > 0: drawpixels('red')
       sleep(1)

#
#       return evse_consumption, 0, 0

    return evse_consumption, evse_energy, evse_temp



######################
def read_shelly_data():
#  strip[0] = (1,0,0) # red=255, green and blue are 0
#  strip.write() # send the data from RAM down the wire

  try:
    response = urequests.get('http://192.168.1.33/status')
    json_data = json.loads(response.text)
    response.close()
    shelly_power = json_data['meters'][0]['power']
    shelly_temp = json_data['tmp']['tC']

#    print (datetime.now().strftime("%H:%M:%S:%f"), "SHELLY:", "{:.1f}".format(shelly_power), "W consumption", "Temperature", "{:.1f}".format(shelly_temp), "Celcius,")
  except:
    shelly_power = -1
    shelly_temp = -1
  return shelly_power, shelly_temp



#################### Switch the Shelly relay and double check it responded
def switch_relay(shelly_state):
    if solar_production > 0: drawpixels('yellow')

    shelly_reply = "pending"
    loopnum = 0

    while shelly_state != shelly_reply:

        # Ask shelly if it is on? ison is either 1 or 0.
        try:
            response = urequests.get('http://192.168.1.33/relay/0')
            json_data = json.loads(response.text)
            response.close()
            ison = json_data['ison']
        except:
            print("AND TIMED OUT CHECKING SHELLY STATE  ")
            ison = -1

        if ison == 1 and shelly_state == "off":
            print("Shelly is on, turning off.")
            send_switch(shelly_state)
        elif ison == 0 and shelly_state == "on":
            print("Shelly is off, turning on.")
            send_switch(shelly_state)
        elif ison == 1:
            shelly_reply = "on"
            print("Shelly is on")
        elif ison == 0:
            shelly_reply = "off"
            print("Shelly is off")
        else:
            print("FAILED TO GET CURRENT SHELLY STATE  ")
            if solar_production > 0: drawpixels('red')
        # counts the number of loops
        loopnum +=1
        if loopnum >= 10:
            # Give up and make the reply = state to exit the loop
            shelly_reply = shelly_state


        sleep(0.5)
        #print("Time, Solar, Power, Shelly, EVSE, evse_min_solar, grid_draw, heating_done, Boot time, Errcount")
        # Now it loops to see if the reply matches the expected state
    drawpixels('')
    return

###################################################################
def send_switch(shelly_state):
    url = "http://192.168.1.33/relay/0?turn=" + shelly_state
    try:
         print("Sending the switching request:", shelly_state)
         response = urequests.get(url)
         response.close()
    except:
         print("REQUEST TO SHELLY TIMED OUT  ")
    return

############################################################
#def drawpixels(solar, power, evse, brightness):
def drawpixels(status):
    brightness = 10
    NUMBER_PIXELS = 25 #25 -1 less, since numbering starts at 0
    LED_PIN = 8

    evse = evse_consumption + shelly_power
    strip = NeoPixel(Pin(LED_PIN), NUMBER_PIXELS)

    ledpower = (power_consumption/6000) * NUMBER_PIXELS
    ledsolar = (solar_production/6000) * NUMBER_PIXELS
    ledevse = (evse/6000) * NUMBER_PIXELS

#    first_pixel = 1 # set to 0 if no status update
#    else:
#        first_pixel = 0 # set to 0 if no status update

    for i in range(0, NUMBER_PIXELS):
        if i < int(ledpower):
            R = brightness # red=255, green and blue are 0
        elif i == int(ledpower):
            R = (ledpower - int(ledpower)) * brightness
        elif i > int(ledpower):
            R = 0

        if i < int(ledsolar):
            G = brightness # red=255, green and blue are 0
        elif i == int(ledsolar):
            G = (ledsolar - int(ledsolar)) * brightness
        elif i > int(ledsolar):
            G = 0

        if i < int(ledevse):
            B = brightness # red=255, green and blue are 0
            G = 0
        elif i == int(ledevse):
            B = (ledevse - int(ledevse)) * brightness
        elif i > int(ledevse):
            B = 0

        if (R == 0 and G == 0 and B == 0) or i == NUMBER_PIXELS-1:
           if status == "magenta":
              strip[i] = (1,0,1)
              strip.write()
              return
           elif status == "cyan":
              strip[i] = (0,1,1)
              strip.write()
              return
           elif status == "yellow":
              strip[i] = (1,1,0)
              strip.write()
              return
           elif status == "blue":
              strip[i] = (0,0,1)
              strip.write()
              return
           elif status == "red":
              strip[i] = (1,0,0)
              strip.write()
              return
        elif R == 0 and G == 0 and B == 0:
            return

        strip[i] = (int(R),int(G),int(B)) # red=255, green and blue are 0
    strip.write() # send the data from RAM down the wire
    return()

###############################################################################
###############################################################################

#from machine import WDT
#wdt = WDT(timeout=180000)  # enable watchdog timer with a timeout of 180s
#wdt.feed()


rtc = RTC()
t = rtc.datetime()
do_connect() # to wifi
syncnettime()



consumption_today = 0
#evse_consumption = 0
evse_consumption = -1
evse_energy = -1
log_minute = t[5]    # need t = rtc.datetime() just above
night_reset = 0
power_consumption = 0
shelly_temp = 0
shelly_power = 0
solar_production = 0
solar_today = 0
voltage = 240

evse_start_solar = 1000
evse_min_solar = 400
evse_min_power = 1600


t = rtc.datetime()
print("Starting the main loop")

boottime = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(t[0], t[1], t[2], t[4], t[5], t[6])
print("Time: " + boottime)


strip.fill((0,0,0))  #Clears the neopixels to stop initial wifi logging showing.
strip.write()

# this is a delay to leave relay off for a bit after switching off, avoids flicking on then off when EVSE takes all the power at turn on.
# it also avoid large grid draw exactly on the hour during the first turn on.
#loops_till_start = random.randint(1, 100)
loops_till_start = 0

last_consumption = power_consumption
last_solar = solar_production
last_evse = evse_consumption

try:
  # Allows an exception to catch errors and continue running.
  while 1: # Run forever
    #get the current solar production and consumption data
    shelly_power, shelly_temp = read_shelly_data()
    evse_consumption, evse_energy, evse_temp = read_evse_data(evse_consumption)
    solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage = read_production_data()

    publish_mqtt("solar/export")  # send data for EVSE and general solar/consumption

    drawpixels('')
    gc.collect()

    t = rtc.datetime()
    timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
    print(timestamp, "Solar", solar_production, "Power", power_consumption, "Shelly", shelly_power, "EVSE", evse_consumption, "EVSE min solar", evse_min_solar, "Grid draw", grid_draw, "heating_done", heating_done, "Boot", boottime, "Err", errcount)

    if t[5] != log_minute:
        # this checks if Shelly has been turned on when it should be off, and add 600W grid_draw
        shelly_power, shelly_temp = read_shelly_data()
        if shelly_power > 100:
             grid_draw = grid_draw + 700
             start_hour = 6
        switch_relay("off")  # checks the shelly relay really is off, and turns it off

    if power_consumption > last_consumption + 100 or \
    power_consumption < last_consumption - 100 or \
    solar_production > last_solar + 150 or \
    solar_production < last_solar - 150 or \
    evse_consumption > last_evse + 150 or \
    evse_consumption < last_evse - 150 or \
    t[5] != log_minute:
       publish_mqtt("csvlog")
       t = rtc.datetime()
       log_minute = t[5]
       last_consumption = power_consumption
       last_solar = solar_production
       last_evse = evse_consumption


    # this calculates if there's enough spare solar power to run
    extra_power = solar_production+grid_draw-power_consumption

    ###################################
    # this starts the heater if there's >'runpower' W excess power, and it's >= start_hour. The start_hour clause tried to optimise when solar should be available.

    t = rtc.datetime()
    if (extra_power > run_power and t[4] >= start_hour and loops_till_start < 1)\
    or (grid_draw > 1 and solar_production > evse_consumption and evse_consumption > run_power and t[4] >= start_hour and loops_till_start < 1):


        publish_mqtt("csvlog")
        switch_relay("on")
        night_reset = 1

        # writes to the logfile before and after turning off the switch
        shelly_power, shelly_temp = read_shelly_data()
        evse_consumption, evse_energy, evse_temp = read_evse_data(evse_consumption)
        solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage = read_production_data()

        publish_mqtt("csvlog")
        t = rtc.datetime()
        log_minute = t[5]



        ##################################
        # and continues running while there's enough solar.

        while solar_production + grid_draw > power_consumption\
        or (grid_draw > 1 and solar_production + grid_draw > evse_consumption and (solar_production + grid_draw) > (power_consumption - evse_consumption)):

            #wdt.feed()
            sleep(2) #2 seconds

            # AND now get fresh data from the solar system
            shelly_power, shelly_temp = read_shelly_data()
            evse_consumption, evse_energy, evse_temp = read_evse_data(evse_consumption)
            solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage = read_production_data()

            publish_mqtt("solar/export")

            drawpixels('')
            gc.collect()

            t = rtc.datetime()
            timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
            #print(timestamp, solar_production, power_consumption, shelly_power, evse_consumption, grid_draw, heating_done, boottime, errcount)
        #    print(timestamp, solar_production, power_consumption, shelly_power, evse_consumption, evse_min_solar, grid_draw, heating_done, boottime, errcount)
            print(timestamp, "Solar", solar_production, "Power", power_consumption, "Shelly", shelly_power, "EVSE", evse_consumption, "EVSE min solar", evse_min_solar, "Grid draw", grid_draw, "heating_done", heating_done, "Boot", boottime, "Err", errcount)


            # This part checks if the relay is on once a minute (while it should be on), and if it is off, turns it on.
            if t[5] != log_minute:
                # this checks if Shelly has been turned off when it should be on, and resets grid_draw to 0.
                shelly_power, shelly_temp = read_shelly_data()
                if shelly_power < 100: grid_draw = 0

                # checks the shelly relay really is on, and turns it on
                switch_relay("on")
                # check to see if power consumption is less than element size, and count minutes, to check heating completed
                if shelly_power < 100  and solar_production + grid_draw > run_power:
                     heating_done = heating_done+1
                     print("Hot water finished (minutes):", heating_done)
                     if heating_done > 5: grid_draw = 0



            if power_consumption > last_consumption + 100 or \
            power_consumption < last_consumption - 100 or \
            solar_production > last_solar + 150 or \
            solar_production < last_solar - 150 or \
            evse_consumption > last_evse + 150 or \
            evse_consumption < last_evse - 150 or \
            t[5] != log_minute:
                 publish_mqtt("csvlog")
                 t = rtc.datetime()
                 log_minute = t[5]
                 last_consumption = power_consumption
                 last_solar = solar_production
                 last_evse = evse_consumption


        # And exits the loop turning off the shelly
        else:
            #"WHOOPS TOO MUCH CONSUMPTION")
            publish_mqtt("csvlog")
            switch_relay("off")

            #wdt.feed()
            sleep(2)
            # writes to the logfile before and after turning off the switch
            shelly_power, shelly_temp = read_shelly_data()
            evse_consumption, evse_energy, evse_temp = read_evse_data(evse_consumption)
            solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage = read_production_data()

            publish_mqtt("csvlog")
            t = rtc.datetime()
            log_minute = t[5]
            loops_till_start = 2  # this does X loops as a delay before it turns on again, to prevent switch telegraphing

            #wdt.feed()
            sleep(3)

    elif solar_production <= 0:
        # IT'S NIGHT TIME NOW.
        #wdt.feed()
        sleep(5)

        # just before midnight reset max_power, and set the start time for tomorrow based on whether power consumption < 1800w while relay on (presumably heating completed for > 5 minutes)
        t = rtc.datetime()
        if t[4] == 0 and t[5] >= 0 and night_reset == 1:
            loops_till_start = random.randint(10, 100)  # delay 1st start by RANDOM number of loops
            pin_led.off() #reset on board LED error indicator
            if heating_done > 90:
                 start_hour = 10
                 grid_draw = 0
            elif heating_done > 5:
                 start_hour = 9
                 grid_draw = 0
            else:
                 start_hour = 8
                 grid_draw = grid_draw + 525
            heating_done = 0
            night_reset = 0
            evse_min_solar = 800
            syncnettime()

    else:
        # this runs if there is solar, but we're waiting to start the hot water heating
        night_reset = 1

        t = rtc.datetime()
        if (extra_power > run_power and t[4] >= start_hour and loops_till_start > 0) \
        or (grid_draw > 1 and solar_production > evse_consumption and evse_consumption > run_power and t[4] >= start_hour and loops_till_start > 0):
            loops_till_start = loops_till_start - 1
            print(loops_till_start)

        #wdt.feed()
        sleep(3)




#except ValueError:
#    print("Whoops, maybe a devision by zero. Sleep 5")
#    sleep(5)

except KeyboardInterrupt:
   print("Keyboardinterrupt caught")
#   event.set()    # tells the RGB thread to exit
#   print("Turn off the Shelly hot water switch...")
#   url = "http://192.168.1.33/relay/0?turn=off"
#   response = urequests.get(url)    # turns off the shelly switch
#   print("Clean up the GPIOs...")
##   GPIO.cleanup()
   print("Exit")
   #wdt.deinit()
#   sys.exit()
#
#Thanks so much to Uwe Moslehner in the Enphase Users + Owners FB group for the example of Token Auth working on D7 firmware.

# Hot water element size in watts + 300 to avoid on/off cycling.
run_power = 2000         # size of the hot water element + 200 W
grid_draw = 0            # this is the baseline added to solar production to offset a series of poor solar production days
start_hour = 10          # hours post midnight before switching starts, to avoid telegraphing at sun comes up
heating_done = 0         # minutes of relay on with power < element (surrogate marked for themostat off and heating done)
voltage = 240            # set here to solve json float problems

import os
import sys #allows use of sys.exit()
import urequests
import network
from umqtt.simple import MQTTClient
from utime import sleep
from machine import Pin, I2C, RTC
from neopixel import NeoPixel
import json
import random  #for the random start delay
import ntptime
import gc
import secrets


#Make these global to keep pixel status updates easy
solar_production = 0
power_consumption = 0
evse_consumption = 0
shelly_power = 0

#max_freq sets the maximum frequency in Hz and accepts the values 20000000, 40000000, 80000000, 160000000, and 240000000
#machine.freq(160000000)



NUMBER_PIXELS = 25
LED_PIN = 8
strip = NeoPixel(Pin(LED_PIN), NUMBER_PIXELS)

pin_led = Pin(10, mode=Pin.OUT)
pin_led.off()

network.country("AU")
sta_if = network.WLAN(network.STA_IF)
sta_if.active(False) # TOGGLING THIS PREVENTS "OSError: Wifi Internal Error"
sta_if.active(True)
#sta_if.config(pm=sta_if.PM_NONE) # disable power management, seems to need active(TRUE) first
#sta_if.config(pm=sta_if.PM_PERFORMANCE) # disable power management, seems to need active(TRUE) first
sta_if.config(pm=sta_if.PM_POWERSAVE) # disable power management, seems to need active(TRUE) first
loopnum = 0
errcount = 0

################################
def npixel(i,red,green,blue):
#    i = i -6
    if i > 24: i = 24
    strip[i] = (red,green,blue) # red=255, green and blue are 0
    strip.write() # send the data from RAM down the wire
    return


#################################
def do_connect():
  loopnum = 0

  while not sta_if.isconnected():
     loopnum = 0
     try:
         sta_if.active(False)
         sta_if.active(True)
         sta_if.config(txpower=10)
         sta_if.connect(secrets.SSID, secrets.wifi_password)
         print('Maybe connected now: {}...'.format(sta_if.status()))
         sleep(1)
     except:
         print("well that attempt failed")
         sta_if.disconnect()
         sta_if.active(False)

     while loopnum < 25:
         print('Got status {}...'.format(sta_if.status()))
         if sta_if.status() == 2:  #Magenta
             npixel(loopnum,1,0,1)
         elif sta_if.status() == 1001: #Yellow, Connecting
             npixel(loopnum,1,1,0)
         elif sta_if.status() == 202: #Cyan, Password error
             npixel(loopnum,0,1,1)
         elif sta_if.status() == 1000: #Green, Idle/waiting
             npixel(loopnum,0,1,0)
         elif sta_if.status() == 203: #Blue, Association fail
             npixel(loopnum,0,0,1)
         elif sta_if.status() == 1010: #CONNECTED
             npixel(loopnum,1,1,1)
             sleep(1)
             break
         else:
             npixel(loopnum,1,0,0)  #Red, Some other error

         loopnum = loopnum + 1
         sleep(1)

# Never got error 201 No AP, 200 Timeout, 204 Handshake timeout
     if loopnum >= 25:
         loopnum = 0
         strip.fill((0,0,0))  #Clears the neopixels
         strip.write()

  else:
     if sta_if.status() == 1010: #Connected
         if loopnum > 1: npixel(loopnum,1,1,1)
         print("Wifi is connected")
         sleep(1)
     else:
         print('Wifi connection failed: {}...'.format(sta_if.status()))
         npixel(loopnum,1,0,0)
  return


#########################
def syncnettime():
# https://docs.micropython.org/en/latest/library/machine.RTC.html
  gc.collect()
  for loopnum in range(0, 3):
    try:
      npixel(loopnum,0,0,1)
      print("Getting current time from net")
      response = urequests.get("http://worldtimeapi.org/api/timezone/Australia/Brisbane")
      json_data = json.loads(response.text)
      response.close()
      print(json_data)

      current_time = json_data["datetime"]
      the_date, the_time = current_time.split("T")
      year, month, mday = [int(x) for x in the_date.split("-")]
      the_time = the_time.split(".")[0]
      hours, minutes, seconds = [int(x) for x in the_time.split(":")]

      print(year, month, mday, 0, hours, minutes, seconds, 0)

      #sets the date and time from the extracted JSON data
      rtc.datetime((year, month, mday, 0, hours, minutes, seconds, 0))

      t = rtc.datetime()
      timestamp = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(t[0], t[1], t[2], t[4], t[5], t[6])
      print(timestamp)
    except OSError as err:
#      npixel(loopnum,1,0,0)
      print(err)
      print("OSError:", gc.mem_free())
      if err == "-202": do_connect()
      sleep(loopnum * 2)
    except Exception as err:
      print(err)
      sleep(loopnum * 2)
    except:
      print("Something else went wrong, time syncing failed")
      sleep(loopnum * 2)
    else:
      npixel(loopnum,1,1,1)
      print("Time sync complete")
      sleep(1)
      return()
  npixel(loopnum,1,0,0)
  sleep(3)
  import machine
  machine.reset()
  return()

##############################################################################
#def read_production_data(solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage):
def read_production_data():
  rtc = RTC()
  t = rtc.datetime()
  global solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage
  if solar_production > 0: drawpixels('cyan')

  #url = 'http://envoy.local/production.json'
  url = 'https://192.168.1.101/production.json'

    # NOTE: I was getting connect refused when hitting envoy.local, probably due to some router DNS problems, so I set a static IP:
    # Error Connecting: HTTPConnectionPool(host='envoy.local', port=80): Max retries exceeded with url: /production.json (Caused by NewConnectionError('<urequests.packages.urllib3.connection.HTTPConnection object at 0x75cf3ad0>: Failed to establish a new connection: [Errno -2] Name or service not known',))

  solar_today = 0
#  while power_consumption == 0:
  headers = {
  "Accept": "application/json",
  "Authorization": secrets.authtoken,
  }
  try:

      response = urequests.get(url, headers=headers) # self-signed certificate
      json_data = json.loads(response.text)
      response.close()


      solar_production = json_data['production'][1]['wNow']
      voltage = json_data['production'][1]['rmsVoltage']
      solar_today = json_data['production'][1]['whToday']
      power_consumption = json_data['consumption'][0]['wNow']
      consumption_today = json_data['consumption'][0]['whToday']

      solar_today = solar_today / 1000
      consumption_today = consumption_today / 1000


  except:
      t = rtc.datetime()
      timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
      print(timestamp + "Error getting solar reading, now returning")
      global errcount
      errcount = errcount + 1
      #pin_led.on() #use on board LED as error indicator
 
#      timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
#      ev_kw = evse_consumption / 1000
#      ev_kwh = evse_energy / 1000
#      hw_kw = shelly_power / 1000
#      hw_kwh = shelly_temp /1000000
#      display.fill(0)
#      display.text("S:" + "{:.0f}".format(solar_production) + "W  P:" + "{:.0f}".format(power_consumption) + "W", 0, 0, 1)
#      display.text("E:" + "{:.1f}".format(ev_kw) + "kW  " + "{:.1f}".format(ev_kwh) + "kWh", 0, 8, 1)
#      display.text("H:" + "{:.1f}".format(hw_kw) + "kW  " + "{:.1f}".format(hw_kwh) + "kWh", 0, 16, 1)
#      display.text(timestamp + " " + "{:.1f}".format(voltage) + "V", 0, 24, 1)
#      display.show()

      if solar_production > 0: drawpixels('red')
      sleep(1)

#      t = rtc.datetime()
#      timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
      do_connect() #check wifi connected

#      return(solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage)
      return(solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage)


      #  do_connect() #check wifi connected
#  return solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage
  return(solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage)


##############################################
def publish_mqtt(target):
#  strip[0] = (0,1,1) # red=255, green and blue are 0
#  strip.write() # send the data from RAM down the wire

  extra_power = solar_production - (power_consumption - evse_consumption)

  # this sorts out weird spikes in MQTT available power, due to EVSE reporting incorrectly high as it fires up
  if evse_consumption > power_consumption: extra_power = solar_production


  t = rtc.datetime()
  # if evse if off, solar +ve and > evse_start_solar
  if extra_power < evse_min_power and solar_production > evse_start_solar and evse_consumption < 1000 and solar_production > power_consumption-shelly_power and t[4] < 16:
     extra_power = evse_min_power
  # if evse is on, using majority of power and solar > evse_min_solar
  elif extra_power < evse_min_power and evse_consumption > 1000 and evse_consumption/power_consumption > 0.46 and solar_production > evse_min_solar and t[4] < 16:
     extra_power = evse_min_power

#  if extra_power < evse_min_power and evse_consumption > 2200: evse_min_solar = 50

#     print("Setting EVSE to", extra_power, "while available solar is >", evse_min_solar, "and spare solar is not available")

  if target == "csvlog":
    if solar_production > 0: drawpixels('blue')

    t = rtc.datetime()
    timestamp = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(t[0], t[1], t[2], t[4], t[5], t[6])

    mqttstring = timestamp+", "\
            +str("{:.0f}".format(solar_production))+", "\
            +str("{:.0f}".format(power_consumption))+", "\
            +str("{:.0f}".format(shelly_power))+", "\
            +str("{:.1f}".format(shelly_temp))+", "\
            +str("{:.3f}".format(solar_today))+", "\
            +str("{:.3f}".format(consumption_today))+", "\
            +str("{:.1f}".format(voltage))+", "\
            +str("{:.1f}".format(evse_temp))+", "\
            +str("{:.0f}".format(evse_consumption))+", "\
            +str("{:.0f}".format(extra_power))
    mqttdata = mqttstring.encode() #convert to bytearray to send to MQTT
  else:
    mqttdata = "{:.1f}".format(extra_power)

  try:

    client_name = 'ESP32'
    broker_addr = '192.168.1.17'
    mqttc = MQTTClient(client_name, broker_addr, keepalive=60)
    mqttc.connect()

    mqttc.publish(target, mqttdata)
    mqttc.publish("solar/power_consumption","{:.0f}".format(power_consumption))
    mqttc.publish("solar/solar_production","{:.0f}".format(solar_production))
    evse = evse_consumption + shelly_power
    mqttc.publish("solar/evse","{:.0f}".format(evse))
    mqttc.publish("solar/voltage","{:.1f}".format(voltage))
    mqttc.disconnect()


  except:
    if solar_production > 0 and target == "csvlog": drawpixels('red')
    t = rtc.datetime()
    timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
    print("MQTT publishing failed", timestamp)
    if target == "csvlog": do_connect() #check wifi connected

  return()




#################### Gets the OpenEVSE status
def read_evse_data(evse_consumption):
#    strip[0] = (0,0,1) # red=255, green and blue are 0
#    strip.write() # send the data from RAM down the wire

    old_evse_consumption = evse_consumption
    if solar_production > 0: drawpixels('magenta')
    try:

       response = urequests.get('http://192.168.1.102/status', timeout=3)
       json_data = json.loads(response.text)
       response.close()

       evse_energy = json_data['session_energy']
       amp = json_data['amp'] / 1000
       evse_consumption = amp * voltage
       evse_temp = json_data['temp'] / 10
    except:
       evse_energy = -1
       evse_temp = -1
       evse_consumption = old_evse_consumption

       rtc = RTC()
       t = rtc.datetime()
       timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])

       print(timestamp + " Error contacting OpenEVSE")
       if solar_production > 0: drawpixels('red')
       sleep(1)

#
#       return evse_consumption, 0, 0

    return evse_consumption, evse_energy, evse_temp



######################
def read_shelly_data():
#  strip[0] = (1,0,0) # red=255, green and blue are 0
#  strip.write() # send the data from RAM down the wire

  try:
    response = urequests.get('http://192.168.1.33/status')
    json_data = json.loads(response.text)
    response.close()
    shelly_power = json_data['meters'][0]['power']
    shelly_temp = json_data['tmp']['tC']

#    print (datetime.now().strftime("%H:%M:%S:%f"), "SHELLY:", "{:.1f}".format(shelly_power), "W consumption", "Temperature", "{:.1f}".format(shelly_temp), "Celcius,")
  except:
    shelly_power = -1
    shelly_temp = -1
  return shelly_power, shelly_temp



#################### Switch the Shelly relay and double check it responded
def switch_relay(shelly_state):
    if solar_production > 0: drawpixels('yellow')

    shelly_reply = "pending"
    loopnum = 0

    while shelly_state != shelly_reply:

        # Ask shelly if it is on? ison is either 1 or 0.
        try:
            response = urequests.get('http://192.168.1.33/relay/0')
            json_data = json.loads(response.text)
            response.close()
            ison = json_data['ison']
        except:
            print("AND TIMED OUT CHECKING SHELLY STATE  ")
            ison = -1

        if ison == 1 and shelly_state == "off":
            print("Shelly is on, turning off.")
            send_switch(shelly_state)
        elif ison == 0 and shelly_state == "on":
            print("Shelly is off, turning on.")
            send_switch(shelly_state)
        elif ison == 1:
            shelly_reply = "on"
            print("Shelly is on")
        elif ison == 0:
            shelly_reply = "off"
            print("Shelly is off")
        else:
            print("FAILED TO GET CURRENT SHELLY STATE  ")
            if solar_production > 0: drawpixels('red')
        # counts the number of loops
        loopnum +=1
        if loopnum >= 10:
            # Give up and make the reply = state to exit the loop
            shelly_reply = shelly_state


        sleep(0.5)
        #print("Time, Solar, Power, Shelly, EVSE, evse_min_solar, grid_draw, heating_done, Boot time, Errcount")
        # Now it loops to see if the reply matches the expected state
    drawpixels('')
    return

###################################################################
def send_switch(shelly_state):
    url = "http://192.168.1.33/relay/0?turn=" + shelly_state
    try:
         print("Sending the switching request:", shelly_state)
         response = urequests.get(url)
         response.close()
    except:
         print("REQUEST TO SHELLY TIMED OUT  ")
    return

############################################################
#def drawpixels(solar, power, evse, brightness):
def drawpixels(status):
    brightness = 10
    NUMBER_PIXELS = 25 #25 -1 less, since numbering starts at 0
    LED_PIN = 8

    evse = evse_consumption + shelly_power
    strip = NeoPixel(Pin(LED_PIN), NUMBER_PIXELS)

    ledpower = (power_consumption/6000) * NUMBER_PIXELS
    ledsolar = (solar_production/6000) * NUMBER_PIXELS
    ledevse = (evse/6000) * NUMBER_PIXELS

#    first_pixel = 1 # set to 0 if no status update
#    else:
#        first_pixel = 0 # set to 0 if no status update

    for i in range(0, NUMBER_PIXELS):
        if i < int(ledpower):
            R = brightness # red=255, green and blue are 0
        elif i == int(ledpower):
            R = (ledpower - int(ledpower)) * brightness
        elif i > int(ledpower):
            R = 0

        if i < int(ledsolar):
            G = brightness # red=255, green and blue are 0
        elif i == int(ledsolar):
            G = (ledsolar - int(ledsolar)) * brightness
        elif i > int(ledsolar):
            G = 0

        if i < int(ledevse):
            B = brightness # red=255, green and blue are 0
            G = 0
        elif i == int(ledevse):
            B = (ledevse - int(ledevse)) * brightness
        elif i > int(ledevse):
            B = 0

        if (R == 0 and G == 0 and B == 0) or i == NUMBER_PIXELS-1:
           if status == "magenta":
              strip[i] = (1,0,1)
              strip.write()
              return
           elif status == "cyan":
              strip[i] = (0,1,1)
              strip.write()
              return
           elif status == "yellow":
              strip[i] = (1,1,0)
              strip.write()
              return
           elif status == "blue":
              strip[i] = (0,0,1)
              strip.write()
              return
           elif status == "red":
              strip[i] = (1,0,0)
              strip.write()
              return
        elif R == 0 and G == 0 and B == 0:
            return

        strip[i] = (int(R),int(G),int(B)) # red=255, green and blue are 0
    strip.write() # send the data from RAM down the wire
    return()

###############################################################################
###############################################################################

#from machine import WDT
#wdt = WDT(timeout=180000)  # enable watchdog timer with a timeout of 180s
#wdt.feed()


rtc = RTC()
t = rtc.datetime()
do_connect() # to wifi
syncnettime()



consumption_today = 0
#evse_consumption = 0
evse_consumption = -1
evse_energy = -1
log_minute = t[5]    # need t = rtc.datetime() just above
night_reset = 0
power_consumption = 0
shelly_temp = 0
shelly_power = 0
solar_production = 0
solar_today = 0
voltage = 240

evse_start_solar = 1000
evse_min_solar = 400
evse_min_power = 1600


t = rtc.datetime()
print("Starting the main loop")

boottime = '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(t[0], t[1], t[2], t[4], t[5], t[6])
print("Time: " + boottime)


strip.fill((0,0,0))  #Clears the neopixels to stop initial wifi logging showing.
strip.write()

# this is a delay to leave relay off for a bit after switching off, avoids flicking on then off when EVSE takes all the power at turn on.
# it also avoid large grid draw exactly on the hour during the first turn on.
#loops_till_start = random.randint(1, 100)
loops_till_start = 0

last_consumption = power_consumption
last_solar = solar_production
last_evse = evse_consumption

try:
  # Allows an exception to catch errors and continue running.
  while 1: # Run forever
    #get the current solar production and consumption data
    shelly_power, shelly_temp = read_shelly_data()
    evse_consumption, evse_energy, evse_temp = read_evse_data(evse_consumption)
    solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage = read_production_data()

    publish_mqtt("solar/export")  # send data for EVSE and general solar/consumption

    drawpixels('')
    gc.collect()

    t = rtc.datetime()
    timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
    print(timestamp, "Solar", solar_production, "Power", power_consumption, "Shelly", shelly_power, "EVSE", evse_consumption, "EVSE min solar", evse_min_solar, "Grid draw", grid_draw, "heating_done", heating_done, "Boot", boottime, "Err", errcount)

    if t[5] != log_minute:
        # this checks if Shelly has been turned on when it should be off, and add 600W grid_draw
        shelly_power, shelly_temp = read_shelly_data()
        if shelly_power > 100:
             grid_draw = grid_draw + 700
             start_hour = 6
        switch_relay("off")  # checks the shelly relay really is off, and turns it off

    if power_consumption > last_consumption + 100 or \
    power_consumption < last_consumption - 100 or \
    solar_production > last_solar + 150 or \
    solar_production < last_solar - 150 or \
    evse_consumption > last_evse + 150 or \
    evse_consumption < last_evse - 150 or \
    t[5] != log_minute:
       publish_mqtt("csvlog")
       t = rtc.datetime()
       log_minute = t[5]
       last_consumption = power_consumption
       last_solar = solar_production
       last_evse = evse_consumption


    # this calculates if there's enough spare solar power to run
    extra_power = solar_production+grid_draw-power_consumption

    ###################################
    # this starts the heater if there's >'runpower' W excess power, and it's >= start_hour. The start_hour clause tried to optimise when solar should be available.

    t = rtc.datetime()
    if (extra_power > run_power and t[4] >= start_hour and loops_till_start < 1)\
    or (grid_draw > 1 and solar_production > evse_consumption and evse_consumption > run_power and t[4] >= start_hour and loops_till_start < 1):


        publish_mqtt("csvlog")
        switch_relay("on")
        night_reset = 1

        # writes to the logfile before and after turning off the switch
        shelly_power, shelly_temp = read_shelly_data()
        evse_consumption, evse_energy, evse_temp = read_evse_data(evse_consumption)
        solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage = read_production_data()

        publish_mqtt("csvlog")
        t = rtc.datetime()
        log_minute = t[5]



        ##################################
        # and continues running while there's enough solar.

        while solar_production + grid_draw > power_consumption\
        or (grid_draw > 1 and solar_production + grid_draw > evse_consumption and (solar_production + grid_draw) > (power_consumption - evse_consumption)):

            #wdt.feed()
            sleep(2) #2 seconds

            # AND now get fresh data from the solar system
            shelly_power, shelly_temp = read_shelly_data()
            evse_consumption, evse_energy, evse_temp = read_evse_data(evse_consumption)
            solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage = read_production_data()

            publish_mqtt("solar/export")

            drawpixels('')
            gc.collect()

            t = rtc.datetime()
            timestamp = '{:02d}:{:02d}:{:02d}'.format(t[4], t[5], t[6])
            #print(timestamp, solar_production, power_consumption, shelly_power, evse_consumption, grid_draw, heating_done, boottime, errcount)
        #    print(timestamp, solar_production, power_consumption, shelly_power, evse_consumption, evse_min_solar, grid_draw, heating_done, boottime, errcount)
            print(timestamp, "Solar", solar_production, "Power", power_consumption, "Shelly", shelly_power, "EVSE", evse_consumption, "EVSE min solar", evse_min_solar, "Grid draw", grid_draw, "heating_done", heating_done, "Boot", boottime, "Err", errcount)


            # This part checks if the relay is on once a minute (while it should be on), and if it is off, turns it on.
            if t[5] != log_minute:
                # this checks if Shelly has been turned off when it should be on, and resets grid_draw to 0.
                shelly_power, shelly_temp = read_shelly_data()
                if shelly_power < 100: grid_draw = 0

                # checks the shelly relay really is on, and turns it on
                switch_relay("on")
                # check to see if power consumption is less than element size, and count minutes, to check heating completed
                if shelly_power < 100  and solar_production + grid_draw > run_power:
                     heating_done = heating_done+1
                     print("Hot water finished (minutes):", heating_done)
                     if heating_done > 5: grid_draw = 0



            if power_consumption > last_consumption + 100 or \
            power_consumption < last_consumption - 100 or \
            solar_production > last_solar + 150 or \
            solar_production < last_solar - 150 or \
            evse_consumption > last_evse + 150 or \
            evse_consumption < last_evse - 150 or \
            t[5] != log_minute:
                 publish_mqtt("csvlog")
                 t = rtc.datetime()
                 log_minute = t[5]
                 last_consumption = power_consumption
                 last_solar = solar_production
                 last_evse = evse_consumption


        # And exits the loop turning off the shelly
        else:
            #"WHOOPS TOO MUCH CONSUMPTION")
            publish_mqtt("csvlog")
            switch_relay("off")

            #wdt.feed()
            sleep(2)
            # writes to the logfile before and after turning off the switch
            shelly_power, shelly_temp = read_shelly_data()
            evse_consumption, evse_energy, evse_temp = read_evse_data(evse_consumption)
            solar_production, power_consumption, shelly_power, shelly_temp, solar_today, consumption_today, voltage = read_production_data()

            publish_mqtt("csvlog")
            t = rtc.datetime()
            log_minute = t[5]
            loops_till_start = 2  # this does X loops as a delay before it turns on again, to prevent switch telegraphing

            #wdt.feed()
            sleep(3)

    elif solar_production <= 0:
        # IT'S NIGHT TIME NOW.
        #wdt.feed()
        sleep(5)

        # just before midnight reset max_power, and set the start time for tomorrow based on whether power consumption < 1800w while relay on (presumably heating completed for > 5 minutes)
        t = rtc.datetime()
        if t[4] == 0 and t[5] >= 0 and night_reset == 1:
            loops_till_start = random.randint(10, 100)  # delay 1st start by RANDOM number of loops
            pin_led.off() #reset on board LED error indicator
            if heating_done > 90:
                 start_hour = 10
                 grid_draw = 0
            elif heating_done > 5:
                 start_hour = 9
                 grid_draw = 0
            else:
                 start_hour = 8
                 grid_draw = grid_draw + 525
            heating_done = 0
            night_reset = 0
            evse_min_solar = 800
            syncnettime()

    else:
        # this runs if there is solar, but we're waiting to start the hot water heating
        night_reset = 1

        t = rtc.datetime()
        if (extra_power > run_power and t[4] >= start_hour and loops_till_start > 0) \
        or (grid_draw > 1 and solar_production > evse_consumption and evse_consumption > run_power and t[4] >= start_hour and loops_till_start > 0):
            loops_till_start = loops_till_start - 1
            print(loops_till_start)

        #wdt.feed()
        sleep(3)




#except ValueError:
#    print("Whoops, maybe a devision by zero. Sleep 5")
#    sleep(5)

except KeyboardInterrupt:
   print("Keyboardinterrupt caught")
#   event.set()    # tells the RGB thread to exit
#   print("Turn off the Shelly hot water switch...")
#   url = "http://192.168.1.33/relay/0?turn=off"
#   response = urequests.get(url)    # turns off the shelly switch
#   print("Clean up the GPIOs...")
##   GPIO.cleanup()
   print("Exit")
   #wdt.deinit()
#   sys.exit()
