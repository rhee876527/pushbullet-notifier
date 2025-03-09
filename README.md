# pushbullet-notifier
Simple pushbullet-notifier for Linux desktop.



![Example](https://github.com/rhee876527/pushbullet-notifier/blob/main/example.png?raw=true)



### Why:

The Chrome extension store has ended support for MV2 extensions and the author has no plans to port the Pushbullet extension to MV3 as far as am aware.

So we make our own replacement listener client using the API. And queue incoming notifications to desktop using `notify-send`.



### Requirements: 
`python` and `libnotify`. 

Works on:

![Python 3.13](https://img.shields.io/badge/Python-3.13-brightgreen.svg)


### Benefits:


- Extremely simple - Uses std python libraries for websocket connections to Pushbullet's API.
- Local cache of client pushes.
- Auto-resume from last message & is resilient against network drops.


### Use: Easy as 1,2,3

1. Get API Access Token from https://www.pushbullet.com/#settings/account



2. Create pushbullet client aka $DEVICE_ID.

   ```
   curl -u $PUSHBULLET_API_KEY: -X POST https://api.pushbullet.com/v2/devices \
       -H "Content-Type: application/json" \
       -d '{"nickname": "LinuxPC", "icon": "laptop"}'
   
   ```
 
     from the response `iden` is your `$PUSHBULLET_DEVICE_ID`

3. Run the python app as a daemon service to listen for new pushes


   Configure the environment variables in the service

   ``nano ~/.config/systemd/user/pushbullet-notify.service``
   
   ```
    [Unit]
    Description=Pushbullet Notification Service
    After=graphical-session.target network-online.target
    Requires=graphical-session.target
    
    [Service]
    ExecStartPre=/bin/sleep 15
    ExecStart=%h/.stuff/push.py
    Restart=on-failure
    RestartSec=10
    WorkingDirectory=%h/.stuff
    
    # Pushbullet API
    Environment="PUSHBULLET_API_KEY=o.8ZxSAMPLEpKo8uRp"
    Environment="PUSHBULLET_DEVICE_ID=ujxSAMPLEZ32i"
    
    [Install]
    WantedBy=graphical-session.target

   ```

   and run:


   `systemctl --user start pushbullet-notify.service `




Learn more about the pushbullet API here: https://docs.pushbullet.com/
