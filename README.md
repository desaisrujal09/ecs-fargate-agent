```markdown
# Comprehensive Project Documentation: Autonomous SRE ChatOps Agent for AWS ECS

This document provides a complete, exhaustive record of everything built, configured, debugged, and optimized to develop the serverless Autonomous SRE ChatOps Agent.

---

## 1. Project Overview & Objectives
* **Goal:** Build an event-driven, AI-powered SRE agent capable of autonomously detecting Amazon ECS/Fargate task failures and providing interactive, on-demand troubleshooting via Slack.
* **Core Value:** Reduce Mean Time to Resolution (MTTR) by translating dense container logs into conversational, human-like root cause analysis and actionable preventative measures.

---

## 2. Complete Architecture & Tech Stack

```mermaid
flowchart TD
    subgraph AWS Cloud
        API[API Gateway] -->|Webhook Event| L((AWS Lambda))
        L <-->|Fetch Recent Logs| CW[Amazon CloudWatch]
        L <-->|Analyze Logs & Intent| B[Amazon Bedrock<br>Nova Lite]
        L -->|Publish Automated Alert| SNS[Amazon SNS]
        ECS[ECS / Fargate] -->|Streams Logs| CW
    end
    
    Slack[Slack Workspace] -->|@SRE-Agent Mention| API
    L -->|chat.postMessage| Slack

```

### Component Breakdown & Tools Used

* **Infrastructure as Code & Version Control:**
* **Terraform:** Defines and provisions all underlying AWS cloud infrastructure.
* **GitHub & GitHub Actions:** Source code management and repository hosting.


* **Compute & Webhook Routing:**
* **AWS API Gateway:** Public-facing HTTP REST endpoint receiving inbound webhook payloads from Slack.
* **AWS Lambda (Python 3.x):** The core serverless execution engine hosting `lambda_function.py`.


* **Observability & Alerting:**
* **Amazon CloudWatch Logs:** Source log group (`/ecs/fargate-test-app`) containing container execution streams.

* **Generative AI Engine:**
* **Amazon Bedrock (`amazon.nova-lite-v1:0` - Nova Lite):** Processes log contexts, evaluates user intent, and generates structured responses.

* **Chat Interface:**
* **Slack Events API (`app_mention`):** Captures workspace user interactions.
* **Slack Web API (`chat.postMessage`):** Posts responses back to the operational channel.



---

## 3. Core Implementation & Code Logic (`lambda_function.py`)

The Lambda function is structured into distinct modules to handle different execution pathways:

### A. Robust Payload Parsing (`parse_slack_body`)

* Designed to handle malformed, stringified, or double-encoded JSON payloads from API Gateway and Slack.
* Utilizes a multi-layered fallback strategy:
1. Standard `json.loads()` with nested double-encoding checks.
2. Single-quote replacement (`.replace("'", '"')`) followed by JSON loading.
3. Python `ast.literal_eval` fallback.



### B. Request Routing & Handler (`lambda_handler`)

* **Deduplication Filter:** Intercepts inbound headers for `X-Slack-Retry-Num`. If found, it immediately drops the duplicate event to prevent multi-message response spam.
* **Challenge Handling:** Automatically responds to Slack URL verification challenges.
* **Event Filtering:** Drops bot-authored messages to prevent endless looping.
* **Route Separation:** Splits execution paths between automated ECS crash reports and interactive Slack chat mentions.

### C. Automated Failure Pipeline (`handle_ecs_failure`)

* Polls CloudWatch log streams (`/ecs/fargate-test-app`) with retry loops to retrieve the last 15 log events.
* Sends the log snippet to Amazon Bedrock with a prompt instructing Nova Lite to act as a senior SRE teammate.
* Publishes the resulting structured analysis to an SNS topic.

### D. Interactive ChatOps Pipeline (`handle_interactive_chat`)

* Extracts the user query and fetches live container logs on-demand.
* Evaluates user intent and scope using strict prompt guardrails before calling Bedrock.
* Uses `urllib` to securely invoke Slack's `chat.postMessage` API endpoint using `SLACK_BOT_TOKEN`.

---

## 4. Comprehensive Troubleshooting Log & Edge Cases Solved

Building this real-time pipeline required diagnosing and resolving several distributed system and configuration friction points:

1. **JSON Parsing & Double-Encoding Errors**
* *Problem:* Lambda threw `AttributeError: 'str' object has no attribute 'get'` when processing API Gateway payloads.
* *Solution:* Built the multi-layered `parse_slack_body()` utility.


2. **Slack URL Verification Failures**
* *Problem:* Slack rejected the API Gateway endpoint during setup.
* *Solution:* Fixed a double-slash typo (`//slack/events`) in the Slack Event Subscriptions request URL.


3. **Socket Mode vs. HTTP Webhook Conflict**
* *Problem:* Verified endpoints received no live event traffic.
* *Solution:* Disabled Slack "Socket Mode" in the app settings, which forces traffic over standard HTTP REST endpoints via API Gateway.


4. **Silent Event Drops After Configuration Changes**
* *Problem:* Changing event subscriptions didn't take effect in live channels.
* *Solution:* Realized that modifying Slack bot event subscriptions requires a full manual **Reinstall to Workspace** to synchronize OAuth tokens.


5. **Multi-Message Response Spam (Duplicate Webhooks)**
* *Problem:* Tagging `@SRE-Agent` triggered 3–4 simultaneous duplicate replies.
* *Solution:*
* Handled Slack's 3-second timeout retries by intercepting the `X-Slack-Retry-Num` header.
* Removed the redundant `message.channels` event subscription from Slack, restricting event triggers strictly to `app_mention`.




6. **Variable Scope and NameErrors**
* *Problem:* Cross-contamination of variables between automated alerts and chat handlers caused runtime crashes.
* *Solution:* Cleanly separated variable scoping across distinct functions (`handle_ecs_failure` vs `handle_interactive_chat`).



---

## 5. Prompt Engineering, Persona, & Guardrail Design

To refine the agent's behavior, Amazon Bedrock (Nova Lite) was constrained using specific prompt engineering rules:

* **Senior SRE Persona:** Instructed the model to communicate conversationally, avoid walls of generic text, explain root causes clearly (e.g., detecting Flask development server misconfigurations), and outline concrete preventative steps.
* **Intent-Aware Greeting:** Programmed rules so that casual small talk (e.g., "hi", "hello") triggers a brief, friendly greeting without dumping logs or technical breakdowns.
* **Strict Out-of-Scope Guardrails:** Added a hard boundary ensuring that if a user asks about anything outside the monitored ECS application, the model refuses and responds with an exact matching string: *"Sorry I am not trained to answer this question. Ask me anything about the ECS app."*
* **Token Optimization:** Configured inference parameters with `maxTokens` set between 200–250 and low temperatures (`0.2` to `0.3`) to guarantee concise, deterministic outputs.

```

```