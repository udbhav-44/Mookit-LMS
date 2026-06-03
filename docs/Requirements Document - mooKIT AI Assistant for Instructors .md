# **AI Assistant for Instructors – mooKIT**

# **1\. Objective**

Build an AI-powered Instructor Assistant inside mooKIT that enables instructors to interact with the LMS using natural language through a chat-based interface.

The assistant should help instructors perform common academic and administrative tasks, such as:

* Creating quizzes from uploaded documents  
* Sending announcements  
* Managing lecture publishing workflows  
* Assisting in course management actions

The system should intelligently process instructor requests and perform the required actions using available system APIs/services.

# **2\. High-Level Vision**

Instead of instructors navigating multiple menus inside mooKIT, they should simply type commands such as:

* “Create a quiz from this PDF.”  
* “Send an announcement that today’s class is canceled.”  
* “Publish this lecture under Week 4 on Monday.”

The assistant should:

* Understand the request  
* Identify the required action(s)  
* Execute the required APIs/tools  
* Ask for confirmation where required  
* Return the final result to the instructor

# **3\. Scope**

## **3.1 Chat-Based Instructor Assistant**

The system should provide:

* Chat-based interface  
* Conversation history  
* File upload support  
* Response preview support

## **3.2 Quiz Generation from Documents**

### **Example Flow**

1. Instructor uploads a PDF/DOCX/PPT/TXT file  
2. Instructor types:  
   * “Create a quiz from this document.”  
3. AI:  
   * Extracts text/content  
   * Generates questions  
   * Creates quiz draft  
4. Instructor reviews/edits the quiz  
5. Quiz is saved to mooKIT

### **Supported Question Types**

* MCQ  
* MCSA  
* True/False  
* Fill in the blanks  
* Descriptive questions

## **3.3 Announcement Assistant**

### **Example Inputs**

* “Cancel today’s class.”  
* “Inform students assignment deadline is extended.”  
* “Send reminder about tomorrow’s exam.”

### **Expected Flow**

1. AI drafts announcement  
2. Preview is shown to instructor  
3. Instructor chooses:  
   * Send email  
   * Post in LMS  
4. Announcement is published/sent

## **3.4 Lecture Publishing Assistant**

### **Example Input**

“Upload this video under Week 4 and publish on Monday.”

### **System Should**

* Identify target course/week  
* Upload resource  
* Schedule publishing  
* Generate lecture title  
* Generate lecture description (optional)

# **4\. Functional Requirements**

## **4.1 Authentication & Authorization**

* An authentication and authorization mecahnisn should be in place  
* Course-level permission validation should be enforced

## **4.2 File Uploads**

Supported file formats:

* PDF  
* DOCX  
* PPT/PPTX  
* TXT

Additional Requirements:

* Maximum upload size should be configurable  
* Invalid or unsupported files should be rejected gracefully

## **4.3 API & Service Integration**

The assistant should integrate with existing mooKIT APIs/services wherever possible

## **4.4 Action Confirmation**

The system should request instructor confirmation before performing important actions such as:

* Sending announcements  
* Publishing lectures  
* Publishing quizzes

# **5\. AI Requirements**

The AI assistant should:

* Maintain conversational context within a session  
* Understand references like:  
  * “this PDF”  
  * “that quiz”  
  * “send it to all students”  
* Support multi-step interactions  
* Generate structured and meaningful responses  
* Generate human-readable drafts/previews before final execution

# **6\. Non-Functional Requirements**

## **6.1 Performance**

* Normal chat responses should ideally be generated within a few seconds  
* Long-running tasks should support asynchronous execution with progress updates where possible

## **6.2 Security**

The system should:

* Validate uploaded files  
* Prevent prompt injection attacks where possible  
* Enforce permission validation  
* Use authenticated APIs/services  
* Prevent unauthorized course access

## **6.3 Audit Logs**

The system should store logs for important actions, including:

* User prompt  
* Action performed  
* Tool/API used  
* Timestamp  
* Status/result

# **7\. Important Design Principles**

The assistant should:

* Assist instructors rather than fully replace workflows  
* Avoid executing risky actions without confirmation  
* Always provide previews before publishing/sending content  
* Maintain transparency of actions performed  
* Be extensible for future AI capabilities

# **8\. Expected Deliverables**

* Source code  
* Technical documentation  
* API integration documentation  
* Setup instructions

# **9\. Sample User Flows**

## **Flow 1 \- Quiz Generation**

Instructor uploads PDF with questions  
        ↓  
“Create a quiz”  
        ↓  
AI extracts content  
        ↓  
AI generates questions  
        ↓  
Preview or link to the quiz shown  
        ↓  
Instructor reviews/edits  
        ↓  
Quiz saved in mooKIT

## **Flow 2 \- Announcement**

“Send announcement that today’s class is cancelled”  
        ↓  
AI drafts a message  
        ↓  
Preview shown  
        ↓  
Confirmation  
        ↓  
Announcement sent

## **Flow 3 – Lecture Publishing**

Instructor uploads video  
        ↓  
“Publish this under Week 4 on Monday”  
        ↓  
AI identifies course/week  
        ↓  
Metadata generated  
        ↓  
Preview (or link to the lecture) shown  
        ↓  
Instructor confirms  
        ↓  
Lecture scheduled/published

# 

# **10\. Query**

Can we use g4dn.xlarge Instance on AWS?   
