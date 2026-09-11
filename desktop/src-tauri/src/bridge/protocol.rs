//! Wire types mirroring `core/bridge/protocol.py`.
//!
//! `params`/`result` are kept as untyped `serde_json::Value` deliberately:
//! the Python side is the single source of truth for command schemas
//! (validated there with Pydantic), and the TypeScript layer applies its
//! own typing at the call site. Duplicating every command's shape here
//! would just be a second place for the two languages to drift apart.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Serialize)]
pub struct RequestMessage {
    #[serde(rename = "type")]
    pub kind: &'static str,
    pub id: String,
    pub session: String,
    pub command: String,
    pub params: Value,
}

impl RequestMessage {
    pub fn new(id: String, session: String, command: String, params: Value) -> Self {
        Self {
            kind: "request",
            id,
            session,
            command,
            params,
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct HelloMessage {
    #[allow(dead_code)]
    pub version: String,
    pub session: String,
    #[allow(dead_code)]
    pub pid: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorPayload {
    pub code: String,
    pub message: String,
    #[serde(default)]
    pub details: Value,
}

#[derive(Debug, Deserialize)]
pub struct ResponseMessage {
    pub id: String,
    pub ok: bool,
    #[serde(default)]
    pub result: Value,
    #[serde(default)]
    pub error: Option<ErrorPayload>,
}

#[derive(Debug, Deserialize)]
pub struct EventMessage {
    pub event: String,
    #[serde(default)]
    pub payload: Value,
}

/// The tagged union of every line the sidecar can send us, discriminated by
/// its `type` field. An unrecognized `type` deserializes as `Unknown` rather
/// than failing the whole parse, so one malformed/future message type never
/// takes down the reader loop.
#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum IncomingMessage {
    Hello(HelloMessage),
    Response(ResponseMessage),
    Event(EventMessage),
    #[serde(other)]
    Unknown,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_message_serializes_with_type_field() {
        let request = RequestMessage::new(
            "req-1".to_string(),
            "session-token".to_string(),
            "health.check".to_string(),
            serde_json::json!({}),
        );
        let line = serde_json::to_string(&request).unwrap();
        let parsed: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["type"], "request");
        assert_eq!(parsed["id"], "req-1");
        assert_eq!(parsed["session"], "session-token");
        assert_eq!(parsed["command"], "health.check");
    }

    #[test]
    fn hello_message_deserializes() {
        let line = r#"{"type":"hello","version":"1","session":"tok","pid":123}"#;
        let parsed: IncomingMessage = serde_json::from_str(line).unwrap();
        match parsed {
            IncomingMessage::Hello(hello) => assert_eq!(hello.session, "tok"),
            _ => panic!("expected Hello variant"),
        }
    }

    #[test]
    fn successful_response_deserializes() {
        let line = r#"{"type":"response","id":"req-1","ok":true,"result":{"status":"ok"}}"#;
        let parsed: IncomingMessage = serde_json::from_str(line).unwrap();
        match parsed {
            IncomingMessage::Response(response) => {
                assert!(response.ok);
                assert_eq!(response.result["status"], "ok");
                assert!(response.error.is_none());
            }
            _ => panic!("expected Response variant"),
        }
    }

    #[test]
    fn error_response_deserializes_with_error_payload() {
        let line = r#"{"type":"response","id":"req-1","ok":false,
            "error":{"code":"NOT_FOUND","message":"missing","details":{}}}"#;
        let parsed: IncomingMessage = serde_json::from_str(line).unwrap();
        match parsed {
            IncomingMessage::Response(response) => {
                assert!(!response.ok);
                let error = response.error.expect("error payload");
                assert_eq!(error.code, "NOT_FOUND");
                assert_eq!(error.message, "missing");
            }
            _ => panic!("expected Response variant"),
        }
    }

    #[test]
    fn event_message_deserializes() {
        let line =
            r#"{"type":"event","event":"execution.progress","payload":{"status":"running"}}"#;
        let parsed: IncomingMessage = serde_json::from_str(line).unwrap();
        match parsed {
            IncomingMessage::Event(event) => {
                assert_eq!(event.event, "execution.progress");
                assert_eq!(event.payload["status"], "running");
            }
            _ => panic!("expected Event variant"),
        }
    }

    #[test]
    fn unknown_message_type_does_not_fail_the_whole_parse() {
        let line = r#"{"type":"something_new","foo":"bar"}"#;
        let parsed: IncomingMessage = serde_json::from_str(line).unwrap();
        assert!(matches!(parsed, IncomingMessage::Unknown));
    }

    #[test]
    fn malformed_json_is_rejected() {
        let line = "{not valid json";
        let parsed: Result<IncomingMessage, _> = serde_json::from_str(line);
        assert!(parsed.is_err());
    }
}
