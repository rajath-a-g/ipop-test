import importlib
import unittest
from time import sleep
from unittest.mock import MagicMock, Mock, patch

from controller.framework.CBT import CBT
from controller.framework.CFx import CFX

from controller.modules.Signal import XmppTransport, JidCache


class SignalTest(unittest.TestCase):
    _cm_config = {"NodeId": "1"}
    overlay_descr = {
        "HostAddress": "1.0.0.0",
        "Port": "5222",
        "Username": "test",
        "Password": "admin",
        "AuthenticationMethod": "PASSWORD"
    }

    def setup_vars_mocks(self):
        """
        Setup the variables and the mocks required by the unit tests.
        :return: The signal object and signal dictionary
        """
        cfx_handle = Mock()
        module = importlib.import_module("controller.modules.{0}"
                                         .format("Signal"))
        module_class = getattr(module, "Signal")
        sig_dict = {"Signal": {"Enabled": True,
                               "Overlays": {
                                   "A0FB389": {
                                       "HostAddress": "1.1.1.1",
                                       "Port": "5222",
                                       "Username": "raj",
                                       "Password": "raj",
                                       "AuthenticationMethod": "PASSWORD"
                                   }
                               }
                               },
                    "NodeId": "1234434323"
                    }
        signal = module_class(cfx_handle, sig_dict, "Signal")
        cfx_handle._cm_instance = signal
        cfx_handle._cm_config = sig_dict
        return sig_dict, signal

    def testtransport_start_event_handler(self):
        """
        Test to check the start of the event handler of the signal class.
        """
        self.sig_log = MagicMock()
        transport = XmppTransport.factory(1, self.overlay_descr, self, None, None, None)
        transport.add_event_handler = MagicMock()
        transport.register_handler = MagicMock()
        transport.get_roster = MagicMock()
        transport.start_event_handler(event=None)
        transport.add_event_handler.assert_called_once()
        transport.get_roster.assert_called_once()
        print("Passed : testtransport_start_event_handler")

    def testtransport_connect_to_server(self):
        """
        Test to check the connect to server of the transport instance of the signal class.
        """
        self.sig_log = MagicMock()
        transport = XmppTransport.factory(1, self.overlay_descr, self, None, None, None)
        transport.connect = MagicMock()
        XmppTransport.connect_to_server(transport)
        transport.connect.assert_called_once()
        print("Passed : testtransport_connect_to_server")

    def testtransport_factory(self):
        """
        Test to check the factory method of the transport instance of the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        self.assertTrue(isinstance(
            XmppTransport.factory("1", sig_dict["Signal"]["Overlays"]["A0FB389"], signal, signal._presence_publisher,
                                  None, None), XmppTransport))
        print("Passed : testtransport_factory")

    @patch("controller.modules.Signal.XmppTransport.factory")
    def testsignal_create_transport(self, mock_factory):
        """
        Test to check the create transport method of the signal class.
        """
        cfx_handle = Mock()
        cfx_handle.query_param.return_value = 30
        module = importlib.import_module("controller.modules.{0}"
                                         .format("Signal"))
        module_class = getattr(module, "Signal")
        sig_dict = {"Signal": {"Enabled": True,
                               "Overlays": {
                                   "A0FB389": {
                                       "HostAddress": "1.1.1.1",
                                       "Port": "5222",
                                       "Username": "raj",
                                       "Password": "raj",
                                       "AuthenticationMethod": "PASSWORD"
                                   }
                               }
                               },
                    "NodeId": "1234434323"
                    }
        signal = module_class(cfx_handle, sig_dict, "Signal")
        cfx_handle._cm_instance = signal
        cfx_handle._cm_config = sig_dict
        transport = XmppTransport(sig_dict["Signal"]["Overlays"]["A0FB389"]["Username"],
                                  sig_dict["Signal"]["Overlays"]["A0FB389"]["Password"], sasl_mech="PLAIN")
        mock_factory.return_value = transport
        transport.connect_to_server = MagicMock()
        assert signal._create_transport_instance("1", sig_dict["Signal"]["Overlays"]["A0FB389"], None,
                                                 None) == transport
        print("Passed : testsignal_create_transport")

    def testsignal_handle_remote_action_invoke(self):
        """
        Test to check the handling of remote action with action as invoke in the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        rem_act = {"RecipientCM": "1234434323", "Action": "Sleep", "Params": "None", "OverlayId": "A0FB389",
                   "RecipientId": "1234434323"}
        signal.submit_cbt = MagicMock()
        signal.handle_remote_action("A0FB389", rem_act, "invk")
        signal.submit_cbt.assert_called_once()
        print("Passed : testsignal_handle_remote_action_invoke")

    def testsignal_handle_remote_action_complete(self):
        """
        Test to check the handling of remote action with action as complete in the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        rem_act = {"RecipientCM": "1234434323", "Action": "Sleep", "Params": "None", "OverlayId": "A0FB389",
                   "InitiatorId": "1234434323", "ActionTag": "None", "Status": "Active"}
        signal.complete_cbt = MagicMock()
        signal.handle_remote_action("A0FB389", rem_act, "cmpt")
        signal.complete_cbt.assert_called_once()
        print("Passed : testsignal_handle_remote_action_complete")

    def testtransport_send_message(self):
        """
        Test to check the send message method of transport instance of the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        transport = XmppTransport.factory("1", sig_dict["Signal"]["Overlays"]["A0FB389"], signal,
                                          signal._presence_publisher,
                                          None, None)
        transport.send_msg(signal._presence_publisher, "invk", None)
        print("Passed : testtransport_send_message")

    def testjid_cache_add_lookup_entry(self):
        """
        Test to check the lookup method of the jid-cache of the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        jid_cache = JidCache(signal, 30)
        jid_cache.add_entry("123", "2345")
        assert jid_cache.lookup("123") == "2345"
        print("Passed : testjid_cache_add_lookup_entry")

    def testjid_cache_scavenge(self):
        """
        Test to check the scavenge method of the jid-cache of the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        jid_cache = JidCache(signal, 5)
        jid_cache.add_entry("123", "2345")
        assert jid_cache.lookup("123") == "2345"
        sleep(5)
        jid_cache.scavenge()
        assert jid_cache.lookup("123") is None
        print("Passed : testjid_cache_scavenge")

    def testsignal_req_handler_initiate_remote_action(self):
        """
        Test to check the handling remote action method  with a request of the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        jid_cache = JidCache(signal, 5)
        jid_cache.add_entry("1", "2345")
        transport = XmppTransport.factory("1", sig_dict["Signal"]["Overlays"]["A0FB389"], signal,
                                          signal._presence_publisher,
                                          None, None)
        transport.send_msg = MagicMock()
        signal._circles = {"A0FB389": {"JidCache": jid_cache, "Transport": transport}}
        cbt = CBT()
        cbt.request.params = {"RecipientId": "1", "OverlayId": "A0FB389"}
        signal.req_handler_initiate_remote_action(cbt)
        transport.send_msg.assert_called_once()
        print("Passed : testsignal_req_handler_initiate_remote_action")

    def testsignal_resp_handler_remote_action(self):
        """
        Test to check the handling remote action method  with a response of the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        cbt = CBT()
        cbt.request.params = {"RecipientId": "1", "OverlayId": "A0FB389"}
        jid_cache = JidCache(signal, 5)
        jid_cache.add_entry("1", "2345")
        transport = XmppTransport.factory("1", sig_dict["Signal"]["Overlays"]["A0FB389"], signal,
                                          signal._presence_publisher,
                                          None, None)
        transport.send_msg = MagicMock()
        signal._circles = {"A0FB389": {"JidCache": jid_cache, "Transport": transport}}
        cbt.tag = "1"
        signal.submit_cbt(cbt)
        resp = CBT.Response()
        cbt.response = resp
        rem_act = {"InitiatorId" : "1", "OverlayId" : "A0FB389"}
        signal._remote_acts["1"] = rem_act
        signal.submit_cbt(cbt)
        signal.transmit_remote_act = MagicMock()
        signal.free_cbt = MagicMock()
        signal.resp_handler_remote_action(cbt)
        signal.transmit_remote_act.assert_called_once()
        signal.free_cbt.assert_called_once()
        print("Passed : testsignal_resp_handler_remote_action")

    def testtransmit_remote_act(self):
        """
        Test to check the transmit remote action method of the signal class.
        """
        rem_act = {"InitiatorId": "1", "OverlayId": "A0FB389"}
        sig_dict, signal = self.setup_vars_mocks()
        jid_cache = JidCache(signal, 5)
        jid_cache.add_entry("1", "2345")
        transport = XmppTransport.factory("1", sig_dict["Signal"]["Overlays"]["A0FB389"], signal,
                                          signal._presence_publisher,
                                          None, None)
        transport.send_msg = MagicMock()
        signal._circles = {"A0FB389": {"JidCache": jid_cache, "Transport": transport}}
        signal.transmit_remote_act(rem_act, "1", "invk")
        transport.send_msg.assert_called_once()
        print("Passed : testtransmit_remote_act")

    def testtransmit_remote_act_nopeer_jid(self):
        """
        Test to check the transmit remote action method with no peer jid of the signal class.
        """
        rem_act = {"InitiatorId": "1", "OverlayId": "A0FB389"}
        sig_dict, signal = self.setup_vars_mocks()
        jid_cache = JidCache(signal, 5)
        transport = XmppTransport.factory("1", sig_dict["Signal"]["Overlays"]["A0FB389"], signal,
                                          signal._presence_publisher,
                                          None, None)
        transport.send_presence = MagicMock()
        signal._circles = {"A0FB389": {"JidCache": jid_cache, "Transport": transport, "OutgoingRemoteActs" : {}}}
        signal.transmit_remote_act(rem_act, "1", "invk")
        transport.send_presence.assert_called_once()
        print("Passed : testtransmit_remote_act_nopeer_jid")

    def testprocess_cbt_request_rem_act(self):
        """
        Test to check the process cbt method with a request to initiate a remote action of the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        cbt = CBT()
        cbt.op_type = "Request"
        cbt.request.action = "SIG_REMOTE_ACTION"
        signal.req_handler_initiate_remote_action = MagicMock()
        signal.process_cbt(cbt)
        signal.req_handler_initiate_remote_action.assert_called_once()
        print("Passed : testprocess_cbt_request_rem_act")

    def testprocess_cbt_request_rep_data(self):
        """
        Test to check the process cbt method with a request to report data of the signal class.
        """
        sig_dict, signal = self.setup_vars_mocks()
        cbt = CBT()
        cbt.op_type = "Request"
        cbt.request.action = "SIG_QUERY_REPORTING_DATA"
        signal.req_handler_query_reporting_data = MagicMock()
        signal.process_cbt(cbt)
        signal.req_handler_query_reporting_data.assert_called_once()
        print("Passed : testprocess_cbt_request_rep_data")

    def testprocess_cbt_resp_tag_present(self):
        """
        Test to check the process cbt method with a response with the cbt tag present.
        """
        sig_dict, signal = self.setup_vars_mocks()
        signal._remote_acts = {"1"}
        signal.resp_handler_remote_action = MagicMock()
        cbt = CBT()
        cbt.op_type = "Response"
        cbt.tag = "1"
        signal.process_cbt(cbt)
        signal.resp_handler_remote_action.assert_called_once()
        print("Passed : testprocess_cbt_resp_tag_present")

if __name__ == '__main__':
    unittest.main()
    unittest.doModuleCleanups()
