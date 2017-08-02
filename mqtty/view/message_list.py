# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import paho.mqtt.client as mqtt


def on_connect(client, userdata, flags, rc):
    print("Connected with result code " + str(rc))
    client.subscribe('#')

def on_message(client, userdata, msg):
    print(msg.topic+" "+str(msg.payload))

# Create a websockets client
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

# Connect to the firehose
client.connect('firehose.openstack.org')
# Listen forever
client.loop_forever()

class MessageListView():
    pass

