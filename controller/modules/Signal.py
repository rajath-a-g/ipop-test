# ipop-project
# Copyright 2016, University of Florida
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
import asyncio
import ssl
import time
import threading
from concurrent import futures
from queue import Queue

try:
    import simplejson as json
except ImportError:
    import json
import random
import slixmpp
from slixmpp import ElementBase, register_stanza_plugin, Message, Callback, StanzaPath, JID
from controller.framework.ControllerModule import ControllerModule


class IpopSignal(ElementBase):
    """Representation of SIGNAL's custom message stanza"""
    name = "ipop"
    namespace = "signal"
    plugin_attrib = "ipop"
    interfaces = set(("type", "payload"))


class JidCache:
    def __init__(self, cmod, expiry):
        self._lck = threading.Lock()
        self._cache = {}
        self._sig = cmod
        self._expiry = expiry

    def add_entry(self, node_id, jid):
        ts = time.time()
        with self._lck:
            self._cache[node_id] = (jid, ts)
        return ts

    def scavenge(self, ):
        with self._lck:
            curr_time = time.time()
            keys_to_be_deleted = \
                [key for key, value in self._cache.items() if curr_time - value[1] >= self._expiry]
            for key in keys_to_be_deleted:
                del self._cache[key]

    def lookup(self, node_id):
        jid = None
        with self._lck:
            entry = self._cache.get(node_id)
            if entry:
                jid = entry[0]
        return jid


class XmppTransport(slixmpp.ClientXMPP):
    def __init__(self, jid, password, sasl_mech):
        slixmpp.ClientXMPP.__init__(self, jid, password, sasl_mech=sasl_mech)
        self._overlay_id = None
        # self.overlay_descr = None
        self._sig = None
        self._node_id = None
        self._presence_publisher = None
        self._jid_cache = None
        self._outgoing_rem_acts = None
        self._cbt_to_action_tag = {}  # maps remote action tags to cbt tags
        self._host = None
        self._port = None
        self.event_loop = None

    @staticmethod
    def factory(overlay_id, overlay_descr, cm_mod, presence_publisher, jid_cache,
                outgoing_rem_acts):
        try:
            keyring_installed = False
            import keyring
            keyring_installed = True
        except ImportError as err:
            cm_mod.sig_log("No key-ring found", "LOG_INFO")
        host = overlay_descr["HostAddress"]
        port = overlay_descr["Port"]
        user = overlay_descr.get("Username", None)
        pswd = overlay_descr.get("Password", None)
        auth_method = overlay_descr.get("AuthenticationMethod", "Password")
        if auth_method == "x509" and (user is not None or pswd is not None):
            er_log = "x509 Authentication is enbabled but credentials " \
                     "exists in IPOP configuration file; x509 will be used."
            cm_mod.sig_log(er_log, "LOG_WARNING")
        if auth_method == "x509":
            transport = XmppTransport(None, None, sasl_mech="EXTERNAL")
            transport.ssl_version = ssl.PROTOCOL_TLSv1
            transport.ca_certs = overlay_descr["TrustStore"]
            transport.certfile = overlay_descr["CertDirectory"] + overlay_descr["CertFile"]
            transport.keyfile = overlay_descr["CertDirectory"] + overlay_descr["Keyfile"]
            transport.use_tls = True
        elif auth_method == "PASSWORD":
            if user is None:
                raise RuntimeError("No username is provided in IPOP configuration file.")
            if pswd is None and keyring_installed is True:
                pswd = keyring.get_password("ipop", overlay_descr["Username"])
            if pswd is None:
                print("{0} XMPP Password: ".format(user))
                pswd = str(input())
                if keyring_installed is True:
                    try:
                        keyring.set_password("ipop", user, pswd)
                    except keyring.errors.PasswordSetError as err:
                        cm_mod.sig_log("Failed to store password in keyring. {0}".format(str(err)),
                                       "LOG_ERROR")
            transport = XmppTransport(user, pswd, sasl_mech="PLAIN")
            transport.use_tls = True
            del pswd
        else:
            raise RuntimeError("Invalid authentication method specified in configuration: {0}"
                               .format(auth_method))
        # pylint: disable=protected-access
        transport._host = host
        transport._port = port
        transport._overlay_id = overlay_id
        transport._sig = cm_mod
        transport._node_id = cm_mod._cm_config["NodeId"]
        transport._presence_publisher = presence_publisher
        transport._jid_cache = jid_cache
        transport._outgoing_rem_acts = outgoing_rem_acts
        # event handler for session start and roster update
        transport.add_event_handler("session_start", transport.start_event_handler)
        return transport

    def host(self):
        return self._host

    def start_event_handler(self, event):
        """Registers custom event handlers at the start of XMPP session"""
        self._sig.sig_log("XMPP Signalling started for overlay: {0}".format(self._overlay_id))
        # pylint: disable=broad-except
        try:
            # Notification of peer signon
            self.add_event_handler("presence_available",
                                   self.presence_event_handler)
            # Register IPOP message with the server
            register_stanza_plugin(Message, IpopSignal)
            self.register_handler(
                Callback("ipop", StanzaPath("message/ipop"), self.message_listener))
            # Get the friends list for the user
            asyncio.ensure_future(self.get_roster(), loop=self.loop)
            # Send sign-on presence
            self.send_presence(pstatus="ident#" + self._node_id)
        except Exception as err:
            self._sig.sig_log("XmppTransport: Exception:{0} Event:{1}"
                              .format(err, event), "LOG_ERROR")

    def presence_event_handler(self, presence):
        """
        Handle peer presence event messages
        """
        try:
            presence_sender = presence["from"]
            presence_receiver_jid = JID(presence["to"])
            presence_receiver = str(presence_receiver_jid.user) + "@" \
                                + str(presence_receiver_jid.domain)
            status = presence["status"]
            # self._sig.sig_log("Presence Overlay:{0} Local JID:{1} Msg:{2}".
            #                   format(self._overlay_id, self.boundjid, presence))
            if (presence_receiver == self.boundjid.bare and presence_sender != self.boundjid.full):
                if (status != "" and "#" in status):
                    pstatus, peer_id = status.split("#")
                    if pstatus == "ident":
                        if peer_id == self._sig.config["NodeId"]:
                            return
                        # a notification of a peers node id to jid mapping
                        pts = self._jid_cache.add_entry(node_id=peer_id, jid=presence_sender)
                        self._presence_publisher.post_update(
                            dict(PeerId=peer_id, OverlayId=self._overlay_id,
                                 PresenceTimestamp=pts))
                        self._sig.sig_log("Resolved {0}@{1}->{2}"
                                          .format(peer_id[:7], self._overlay_id, presence_sender))
                        payload = self.boundjid.full + "#" + self._node_id
                        self.send_msg(presence_sender, "announce", payload)
                    elif pstatus == "uid?":
                        # a request for our node id
                        if self._node_id == peer_id:
                            payload = self.boundjid.full + "#" + self._node_id
                            self.send_msg(presence_sender, "uid!", payload)
                    else:
                        self._sig.sig_log("Unrecognized PSTATUS:{0} on overlay:{1}"
                                          .format(pstatus, self._overlay_id), "LOG_WARNING")
        except Exception as err:
            self._sig.sig_log("XmppTransport:Exception:{0} overlay:{1} presence:{2}"
                              .format(err, self._overlay_id, presence), "LOG_ERROR")

    def message_listener(self, msg):
        """
        Listen for matched messages on the xmpp stream, extract the header
        and payload, and takes suitable action.
        """
        try:
            sender_jid = msg["from"]
            self._sig.sig_log("Received message from: {0}".format(sender_jid))
            # discard the message if it was initiated by this node
            if sender_jid == self.boundjid.full:
                return
            # extract header and content
            msg_type = msg["ipop"]["type"]
            msg_payload = msg["ipop"]["payload"]
            self._sig.sig_log("Inside message listener with message: {0}".format(msg))
            if msg_type == "uid!":
                match_jid, matched_uid = msg_payload.split("#")
                # put the learned JID in cache
                self._jid_cache.add_entry(matched_uid, match_jid)
                self._sig.sig_log(
                    "Successfully put the uid {0} with jid {1} in the cache".format(matched_uid, match_jid))
                # send the remote actions that are waiting on JID refresh
                rm_que = self._outgoing_rem_acts.get(matched_uid, Queue())
                while not rm_que.empty():
                    entry = rm_que.get()
                    msg_type, msg_data = entry[0], entry[1]
                    self._sig.sig_log(
                        "Preparing to send message to {0} with type {1} and data {2}".format(match_jid, msg_type,
                                                                                             msg_data))
                    self.send_msg(match_jid, msg_type, json.dumps(msg_data))
                    self._sig.sig_log("Successfully sent message to {0}".format(match_jid))
                    self._sig.sig_log("Sent remote action: {0}".format(msg_payload))
            elif msg_type == "announce":
                peer_jid, peer_id = msg_payload.split("#")
                if peer_id == self._sig.node_id:
                    self._sig.log("UID Announce msg returned to self msg=%s", msg)
                    return
                # a notification of a peers node id to jid mapping
                pts = self._jid_cache.add_entry(node_id=peer_id, jid=peer_jid)
                self._presence_publisher.post_update(
                    dict(PeerId=peer_id, OverlayId=self._overlay_id, PresenceTimestamp=pts))
            elif msg_type in ("invk", "cmpt"):
                rem_act = json.loads(msg_payload)
                self._sig.sig_log("Received a message to {0} with message as: {1}".format(msg_type, msg))
                self._sig.handle_remote_action(self._overlay_id, rem_act, msg_type)
            else:
                self._sig.sig_log("Invalid message type received {0}".format(str(msg)),
                                  "LOG_WARNING")
        except Exception as err:
            self._sig.sig_log("XmppTransport:Exception:{0} msg:{1}".format(err, msg),
                              "LOG_ERROR")

    def send_msg(self, peer_jid, msg_type, payload):
        """Send a message to Peer JID via XMPP server"""
        msg = self.Message()
        msg["to"] = peer_jid
        msg["from"] = self.boundjid.full
        msg["type"] = "chat"
        msg["ipop"]["type"] = msg_type
        msg["ipop"]["payload"] = payload
        self._sig.sig_log("In send_msg with message: {0}".format(msg))
        self.loop.call_soon_threadsafe(msg.send)


    def connect_to_server(self, ):
        try:
            self.connect(address=(self._host, self._port))
            self._sig.sig_log("Starting overlay {0} connection to XMPP server {1}:{2}"
                              .format(self._overlay_id, self._host, self._port))
        except Exception as err:
            self._sig.sig_log("Failed to initialize XMPP transport instanace {}".format(str(err)),
                              "LOG_ERROR")

    def start_process(self):
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        self._sig.sig_log("Started processing in a new thread for host {0}".format(self._host))
        self.loop.set_debug(enabled=True)
        self.loop.run_forever()

    def shutdown(self, ):
        self.loop.stop()
        self.loop.close()
        self.disconnect()


class Signal(ControllerModule):
    def __init__(self, cfx_handle, module_config, module_name):
        super(Signal, self).__init__(cfx_handle, module_config, module_name)
        self._presence_publisher = None
        self._circles = {}
        self._remote_acts = {}
        self._lock = threading.Lock()
        self.request_timeout = self._cfx_handle.query_param("RequestTimeout")
        self._scavenge_timer = time.time()

    def _create_transport_instance(self, overlay_id, overlay_descr, jid_cache, outgoing_rem_acts):
        xport = XmppTransport.factory(overlay_id, overlay_descr, self, self._presence_publisher,
                                      jid_cache, outgoing_rem_acts)
        xport.connect_to_server()
        threading.Thread(target=xport.start_process, daemon=True).start()
        return xport

    def initialize(self):
        self._presence_publisher = self._cfx_handle.publish_subscription("SIG_PEER_PRESENCE_NOTIFY")
        for overlay_id in self.overlays:
            overlay_descr = self.overlays[overlay_id]
            self._circles[overlay_id] = {}
            self._circles[overlay_id]["Announce"] = time.time() + \
                                                    (int(self.config["PresenceInterval"]) * random.randint(1, 3))
            self._circles[overlay_id]["JidCache"] = \
                JidCache(self, self._cm_config["CacheExpiry"])
            self._circles[overlay_id]["OutgoingRemoteActs"] = {}
            self._circles[overlay_id]["Transport"] = \
                self._create_transport_instance(overlay_id, overlay_descr,
                                                self._circles[overlay_id]["JidCache"],
                                                self._circles[overlay_id]["OutgoingRemoteActs"])
        self.sig_log("Module loaded", "LOG_INFO")

    def req_handler_query_reporting_data(self, cbt):
        rpt = {}
        for overlay_id in self.overlays:
            rpt[overlay_id] = {
                "xmpp_host": self._circles[overlay_id]["Transport"].host(),
                "xmpp_username": self._circles[overlay_id]["Transport"].boundjid.full
            }
        cbt.set_response(rpt, True)
        self.complete_cbt(cbt)

    def handle_remote_action(self, overlay_id, rem_act, act_type):
        if not overlay_id == rem_act["OverlayId"]:
            self.sig_log("The Overlay ID in the rcvd remote action conflicts with the local "
                         "configuration. It was discarded: {}".format(rem_act), "LOG_WARNING")
            return
        if act_type == "invk":
            self.invoke_remote_action_on_target(rem_act)
        elif act_type == "cmpt":
            self.complete_remote_action_on_initiator(rem_act)

    def invoke_remote_action_on_target(self, rem_act):
        """ Convert the received remote action into a CBT and invoke it locally """
        # if the intended recipient is offline the XMPP server broadcasts the msg to all
        # matching ejabber ids. Verify recipient using Node ID and discard if mismatch
        if rem_act["RecipientId"] != self.node_id:
            self.sig_log("A mis-delivered remote action was discarded: {0}"
                         .format(rem_act), "LOG_WARNING")
            return
        n_cbt = self.create_cbt(self._module_name, rem_act["RecipientCM"],
                                rem_act["Action"], rem_act["Params"])
        # store the remote action for completion
        self._remote_acts[n_cbt.tag] = rem_act
        self.submit_cbt(n_cbt)
        return

    def complete_remote_action_on_initiator(self, rem_act):
        """ Convert the received remote action into a CBT and complete it locally """
        # if the intended recipient is offline the XMPP server broadcasts the msg to all
        # matching ejabber ids. Verify recipient using Node ID and discard if mismatch
        if rem_act["InitiatorId"] != self.node_id:
            self.sig_log("A mis-delivered remote action was discarded: {0}"
                         .format(rem_act), "LOG_WARNING")
            return
        tag = rem_act["ActionTag"]
        cbt_status = rem_act["Status"]
        pending_cbt = self._cfx_handle._pending_cbts.get(tag, None)
        if pending_cbt:
            pending_cbt.set_response(data=rem_act, status=cbt_status)
            self.complete_cbt(pending_cbt)

    def req_handler_initiate_remote_action(self, cbt):
        """
        Create a new remote action from the received CBT and transmit it to the recepient
        remote_act = dict(OverlayId="",
                          RecipientId="",
                          RecipientCM="",
                          Action="",
                          Params=json.dumps(opaque_msg),
                          # added by Signal
                          InitiatorId="",
                          InitiatorCM="",
                          ActionTag="",
                          Data="",
                          Status="")
        """
        rem_act = cbt.request.params
        peer_id = rem_act["RecipientId"]
        overlay_id = rem_act["OverlayId"]
        if overlay_id not in self._circles:
            cbt.set_response("Overlay ID not found", False)
            self.complete_cbt(cbt)
            return
        rem_act["InitiatorId"] = self.node_id
        rem_act["InitiatorCM"] = cbt.request.initiator
        rem_act["ActionTag"] = cbt.tag
        self.transmit_remote_act(rem_act, peer_id, "invk")

    def resp_handler_remote_action(self, cbt):
        """ Convert the response CBT to a remote action and return to the initiator """
        rem_act = self._remote_acts.pop(cbt.tag)
        peer_id = rem_act["InitiatorId"]
        rem_act["Data"] = cbt.response.data
        rem_act["Status"] = cbt.response.status
        self.transmit_remote_act(rem_act, peer_id, "cmpt")
        self.free_cbt(cbt)

    def transmit_remote_act(self, rem_act, peer_id, act_type):
        """
        Transmit rem act to peer, if Peer JID is not cached queue the rem act and attempt to
        resolve the peer's JID
        """
        olid = rem_act["OverlayId"]
        target_jid = self._circles[olid]["JidCache"].lookup(peer_id)
        transport = self._circles[olid]["Transport"]
        if target_jid is None:
            out_rem_acts = self._circles[olid]["OutgoingRemoteActs"]
            if peer_id not in out_rem_acts.keys():
                out_rem_acts[peer_id] = Queue(maxsize=0)
            out_rem_acts[peer_id].put((act_type, rem_act, time.time()))
            transport.send_presence(pstatus="uid?#" + peer_id)
        else:
            payload = json.dumps(rem_act)
            transport.send_msg(str(target_jid), act_type, payload)
            self.sig_log("Sent remote act to peer ID: {0}\n Payload: {1}"
                         .format(peer_id, payload))

    def process_cbt(self, cbt):
        with self._lock:
            if cbt.op_type == "Request":
                if cbt.request.action == "SIG_REMOTE_ACTION":
                    self.req_handler_initiate_remote_action(cbt)
                elif cbt.request.action == "SIG_QUERY_REPORTING_DATA":
                    self.req_handler_query_reporting_data(cbt)
                else:
                    self.req_handler_default(cbt)
            elif cbt.op_type == "Response":
                if cbt.tag in self._remote_acts:
                    self.resp_handler_remote_action(cbt)
                else:
                    parent_cbt = cbt.parent
                    cbt_data = cbt.response.data
                    cbt_status = cbt.response.status
                    self.free_cbt(cbt)
                    if (parent_cbt is not None and parent_cbt.child_count == 1):
                        parent_cbt.set_response(cbt_data, cbt_status)
                        self.complete_cbt(parent_cbt)

    def timer_method(self):
        with self._lock:
            for overlay_id in self._circles:
                anc = self._circles[overlay_id]["Announce"]
                if time.time() >= anc:
                    self._circles[overlay_id]["Transport"].event_loop.call_soon_threadsafe(lambda: self._circles[overlay_id]["Transport"].send_presence(pstatus="ident#" +
                                                                                 self.node_id))
                    self._circles[overlay_id]["Announce"] = time.time() + \
                                                            (int(self.config["PresenceInterval"]) * random.randint(2,
                                                                                                                   20))
                # self._circles[overlay_id]["JidCache"].scavenge()
                self.scavenge_expired_outgoing_rem_acts(self._circles[overlay_id]
                                                        ["OutgoingRemoteActs"])
            self.scavenge_pending_cbts()

    def terminate(self):
        for overlay_id in self._circles:
            self._circles[overlay_id]["Transport"].shutdown()

    def sig_log(self, msg, level="LOG_DEBUG"):
        self.register_cbt("Logger", level, msg)

    def scavenge_pending_cbts(self):
        scavenge_list = []
        for item in self._cfx_handle._pending_cbts.items():
            if time.time() - item[1].time_submit >= self.request_timeout:
                scavenge_list.append(item[0])
        for tag in scavenge_list:
            pending_cbt = self._cfx_handle._pending_cbts.pop(tag, None)
            if pending_cbt:
                pending_cbt.set_response("The request has expired", False)
                self.complete_cbt(pending_cbt)

    def scavenge_expired_outgoing_rem_acts(self, outgoing_rem_acts):
        # clear out the JID Refresh queue for a peer if the oldest entry age exceeds the limit
        peer_ids = []
        for peer_id in outgoing_rem_acts:
            peer_qlen = outgoing_rem_acts[peer_id].qsize()
            if not outgoing_rem_acts[peer_id].queue:
                continue
            remact_descr = outgoing_rem_acts[peer_id].queue[0]  # peek at the first/oldest entry
            if time.time() - remact_descr[2] >= self.request_timeout:
                peer_ids.append(peer_id)
                self.sig_log("Remote acts scavenged for removal peer id {0} qlength {1}"
                             .format(peer_id, peer_qlen))
        for peer_id in peer_ids:
            rem_act_que = outgoing_rem_acts.pop(peer_id, Queue())
            while not rem_act_que.empty():
                entry = rem_act_que.get()
                if entry[0] == "invk":
                    tag = entry[1]["ActionTag"]
                    pending_cbt = self._cfx_handle._pending_cbts.get(tag, None)
                    if pending_cbt:
                        pending_cbt.set_response("The specified recipient was not found", False)
                        self.complete_cbt(pending_cbt)