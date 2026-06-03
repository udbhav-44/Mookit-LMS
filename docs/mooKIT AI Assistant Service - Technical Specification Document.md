# mooKIT AI Assistant Service Technical Specification Document

Version: 1.0

[Related Document: AI Assistant for Instructors – Requirements Document](https://docs.google.com/document/d/1OVmEqP_Q4rHSCiKDSdL70di_Xc6GBMm_DJ5JXPhz5Bg/edit?usp=sharing)

# **1\. Purpose**

This document defines the technical specification for the mooKIT AI Assistant Service.

The AI Assistant Service will provide AI-powered capabilities to instructors through a conversational interface.

The service will operate independently of any specific mooKIT deployment and should be designed as a reusable service that can be connected to multiple mooKIT instances.

Examples:

* hello.iitk.ac.in  
* learn.online.iitk.ac.in  
* future mooKIT deployments

The service should expose APIs that can be consumed by mooKIT frontend applications.

The production chat interface will be developed by the mooKIT frontend team.

For development and testing purposes, the implementation team may develop a simple sample chat interface.

# **2\. Scope**

The service should support the following capabilities:

## **Phase 1**

* Assessment generation from uploaded documents  
* Announcement generation and publishing  
* Lecture publishing assistance  
* Context-aware conversations  
* File processing  
* AI-powered content generation

The service should not be responsible for production UI implementation.

# **3\. Responsibilities**

## **3.1 AI Assistant Team Responsibilities**

The implementation team is expected to develop:

* AI Assistant Service  
* AI integration layer  
* File processing layer  
* Session management  
* Context management  
* Action execution layer  
* API layer  
* Authentication Mechanism  
* Audit logging  
* Sample UI for testing

## **3.2 mooKIT Team Responsibilities**

The mooKIT team will provide:

* Production chat interface  
* Frontend integration  
* Existing mooKIT APIs  
* Authentication Integration  
* Assessment APIs  
* Announcement APIs  
* Lecture APIs

The production chat interface will communicate with the AI Assistant Service through APIs.

# **4\. Multi-Instance Support**

The service should be designed as a shared service capable of supporting multiple mooKIT deployments.

Examples:

* hello.iitk.ac.in  
* learn.online.iitk.ac.in  
* future mooKIT installations

Every request should contain sufficient information to identify:

* Source mooKIT instance  
* User  
* Course  
* Session

Example:

{  
"instanceId": "hello.iitk.ac.in",  
"userId": 1001,  
"courseId": 501,  
"sessionId": "abc123"  
}

The service should isolate requests belonging to different instances.

# **5\. High-Level Processing Flow**

Instructor  
↓  
mooKIT Chat UI  
↓  
AI Assistant Service  
↓  
AI Provider API  
↓  
Draft Response Generated  
↓  
Confirmation (if required)  
↓  
mooKIT API  
↓  
Action Executed  
↓  
Response Returned

# **6\. Session Management**

Every conversation should belong to a session.

## **Session Attributes**

| Field | Description |
| ----- | ----- |
| sessionId | Unique session identifier |
| userId | Instructor identifier |
| courseId | Course identifier |
| instanceId | mooKIT instance |
| createdAt | Session creation timestamp |
| updatedAt | Last interaction timestamp |

# **7\. Context Management**

The assistant should maintain context during a session.

Example:

User: Create a Assessment from this PDF.

User: Add 5 more questions.

User: Make them harder.

User: Publish it.

The assistant should correctly identify:

* uploaded file  
* generated Assessment   
* generated announcement  
* generated lecture

Context persistence across sessions is not required.

# **8\. File Processing**

## **Supported File Types**

* PDF  
* DOCX  
* DOCX  
* PPT  
* PPTX  
* TXT  
* EXCEL  
* CSV

## **File Processing Flow**

Upload File  
↓  
Validate File  
↓  
Extract Content  
↓  
Store Extracted Content  
↓  
Provide Content to AI

## **Validation Rules**

The system should reject:

* Unsupported file formats  
* Corrupted files  
* Files exceeding configured size limits

Maximum upload size should be configurable.

# **9\. Functional Module: Assessment Generation**

## **Example User Commands**

* Create a Assessment from this document

## **Processing Flow**

Upload Document  
↓  
Generate Assessment Request  
↓  
Extract Content  
↓  
Generate Questions  
↓  
Create Draft Assessment  
↓  
Preview  
↓  
Instructor Review  
↓  
Confirmation  
↓  
Assessment Created

## **Supported Question Types**

* MCQ  
* MCSA  
* True/False  
* Fill in the Blanks  
* Descriptive

## **Expected Output**

The service should generate a Assessment draft that can be previewed and edited before creation.

# **10\. Functional Module: Announcement Assistant**

## **Example Commands**

* Cancel today's class  
* Send a reminder for tomorrow's exam  
* Inform students that the deadline has been extended  
* Inform Section 3 that today’s lab is rescheduled to 5 PM

## **Processing Flow**

User Request  
↓  
Generate Draft  
↓  
Preview  
↓  
Confirmation  
↓  
Publish

# **11\. Functional Module: Lecture Publishing Assistant**

## **Example Commands**

* Upload this video under Week 4  
* Add this lecture to Module 2

## **Processing Flow**

Upload Resource  
↓  
Instruction  
↓  
Generate Metadata  
↓  
Preview  
↓  
Confirmation  
↓  
Publish

## **Metadata Generation**

The assistant may generate:

* Lecture title

# **12\. AI Provider Integration**

The service will use external AI APIs.

Examples:

* OpenAI GPT Models (Preferred)  
* Anthropic Claude  
* Google Gemini

The implementation should allow changing providers with minimal code changes.

No local model hosting is expected.

No GPU infrastructure is required.

# **13\. APIs Required From mooKIT**

The following capabilities are expected to be available through mooKIT APIs.

Actual endpoint URLs, request payloads, and response formats will be provided separately by the mooKIT team.

| Capability | Endpoint |
| ----- | ----- |
| User Information | To be provided |
| Course Information | To be provided |
| Assessment Creation | To be provided |
| Assessment Update | To be provided |
| Assessment Publishing | To be provided |
| Announcement Creation | To be provided |
| Announcement Publishing | To be provided |
| Lecture Creation | To be provided |
| Lecture Publishing | To be provided |

# **14\. APIs Exposed By AI Assistant Service**

The exact endpoint names may be decided during implementation.

The service should expose APIs for:

## **Chat API**

Purpose:

* Receive user prompts  
* Maintain conversation context  
* Return AI responses

Endpoint:

To be finalized

## **File Upload API**

Purpose:

* Upload files  
* Store file metadata  
* Trigger content extraction

Endpoint:

To be finalized

## **Assessment Generation API**

Purpose:

* Generate Assessment drafts  
* Publish on user confirmation

Endpoint:

To be finalized

## **Announcement  API**

Purpose:

* Generate announcement drafts  
* Publish on user confirmation

Endpoint:

To be finalized

## **Lecture API**

Purpose:

* Generate lecture metadata  
* Create Lecture  
* Publish on user confirmation

Endpoint:

To be finalized

# **15\. Authentication & Authorization**

All requests must be authenticated.

The service must validate:

* User identity  
* Course membership  
* Instructor permissions

Unauthorized requests must be rejected.

# **16\. Confirmation Rules**

The following actions require explicit user confirmation:

| Action | Confirmation Required |
| ----- | ----- |
| Publish Assessment | Yes |
| Send Announcement | Yes |
| Publish Lecture | Yes |

No publishing action should occur without confirmation.

# **17\. Audit Logging**

The service should maintain logs for important actions.

Suggested log fields:

* Instance ID  
* User ID  
* Session ID  
* Prompt  
* Action  
* Status  
* Timestamp

Example:

{  
"instanceId": "hello.iitk.ac.in",  
"userId": 1001,  
"sessionId": "abc123",  
"action": "Assessment\_CREATE",  
"status": "SUCCESS"  
}

# **18\. Error Handling**

The service should provide meaningful error responses.

Examples:

* Unsupported file format  
* Permission denied  
* Unable to process request  
* Service temporarily unavailable

The UI should be able to display these messages to users.

# **19\. Security Requirements**

The service should:

* Validate uploaded files  
* Enforce authorization checks  
* Use authenticated API communication  
* Restrict actions to authorized instructors  
* Prevent prompt injection where feasible  
* Log critical actions  
* Protect data exchanged between mooKIT and the service

# **20\. Performance Requirements**

* Typical chat responses should be generated within a few seconds.  
* Long-running operations should be executed asynchronously. May be a queue or similar implementation that provides continuous feedbacks on the current state.  
* The service should support concurrent users across multiple mooKIT instances.

# **21\. Deployment Requirements**

The service should be deployable independently of mooKIT.

Suggested deployment model:

mooKIT Instance 1  
|  
mooKIT Instance 2  
|  
mooKIT Instance N  
|  
v  
AI Assistant Service  
|  
v  
AI Provider APIs

The deployment should allow:

* Multi-instance support

# **22\. Deliverables**

The implementation team should provide:

## **Source Code**

* AI Assistant Service  
* Sample testing UI

## **Documentation**

* Architecture document  
* API documentation  
* Deployment guide  
* Setup instructions

## **Demonstration**

Working demonstrations of:

* Assessment generation  
* Announcement publishing  
* Lecture publishing

# **23\. Assumptions**

* mooKIT APIs for assessments, announcements, lectures,will be available.  
* The production chat interface will be developed separately by the mooKIT frontend team.  
* The AI Assistant Service will expose APIs for frontend integration.  
* External AI APIs will be used.  
* No local model hosting is required.  
* No GPU infrastructure is required.  
* The design should allow future expansion to additional instructor workflows.