INX: The Video Afterlife

The Challenge

Technical and educational videos are useful while you are watching them. The problem starts when you need to find something from the video later.

You might remember that a particular concept was explained, but not where it was discussed. You might remember the topic but not the exact explanation. Going through a long video again just to find one piece of information is not practical.

For this challenge, build an application that takes an educational YouTube video and turns its available transcript or captions into something that can be searched, explored and used for questions.

The application should help a user find information from the video without having to watch the entire video again.

Some examples of questions a user might want to answer are:

* What topics are covered in this video?
* Where was a particular topic discussed?
* What are the main ideas?
* What did the speaker say about a particular concept?
* Can I ask a question about the video and get an answer from it?

A summary by itself is not enough. The system should make the information in the video easier to use.

What the Application Should Do

The basic flow should look something like this:

YouTube Video
      ↓
Transcript / Captions
      ↓
Content Processing
      ↓
Structured Information
      ↓
Interactive Interface
      ↓
Question Answering

The implementation is up to you, but the application needs to cover the following parts.

1. Video Input

The application must accept a YouTube video URL.

It should validate the URL and handle videos that cannot be processed.

For example:

* Invalid YouTube URL
* Unsupported URL
* Video unavailable
* Video with no usable transcript or captions

The user should receive a clear explanation when a video cannot be processed.

You should also decide what happens when a transcript cannot be obtained. The application should handle that case instead of failing with an unexplained error.

2. Transcript and Captions

The transcript or captions available for the video should be the main source of information used by the application.

Information generated from the video should be supported by the available transcript or captions.

The system should not answer a question using unrelated external knowledge and present that answer as something said in the video.

If the transcript does not contain enough information to answer a question, the application should make that clear.

3. Extracting Information

The transcript should be processed into information that is useful to the user.

At a minimum, the application should provide a way to identify:

* Major topics covered in the video
* Important concepts or ideas
* Key points and takeaways
* The general structure of the video

How this is represented is up to the team.

For example, you could use:

* Chapters
* Sections
* Topics
* An interactive timeline
* A topic or concept map
* Relationships between concepts
* Another structure that makes sense for the application

The important part is that the user can understand and navigate the content without having to go through the complete transcript.

4. Exploring the Video

The application should provide a way to explore the information extracted from the video.

For example, a user could:

Open video
   ↓
View major topics
   ↓
Select a topic
   ↓
Read an explanation
   ↓
Explore the related part of the video
   ↓
Ask a question

This is only an example. You are free to design the interaction differently.

The interface should make it easy to move from a broad topic to the relevant information in the video.

5. Questions and Answers

The application must allow the user to ask questions about the selected video.

Answers should be based on the transcript or captions used by the system.

The system should stay within the scope of that video.

For example, if the transcript explains what RAG is but does not discuss a particular implementation detail, the system should not use general model knowledge to fill in the missing information and claim that the video said it.

A good answer should make it possible to understand where the information came from. If your implementation supports timestamps or source excerpts, those can be used to make the answer easier to verify.

Constraints

Source Grounding

The video’s transcript or captions are the primary source for the application.

Generated summaries, topics, explanations and answers should be based on that source.

The system should distinguish between information that is present in the video and information that is not.

Video Processing Limit

The application should have a practical limit on the length of videos it can process.

The limit is up to you, but you should be able to explain why you selected it.

Consider the amount of transcript data, processing time, model usage, API limits and available resources when deciding the limit.

Input and Processing Errors

The application should handle common failure cases, including:

* Invalid YouTube URL
* Unsupported URL
* Video unavailable
* Missing transcript or captions
* Empty transcript
* Unusable transcript
* Transcript retrieval failure
* Processing failure
* Model or API failure

These cases should result in a useful message to the user.

A generic server error or blank screen is not considered proper error handling.

Resource Usage

The solution should be practical to run during the event.

Consider:

* Processing time
* API limits
* Model costs
* Memory and compute requirements
* Storage
* Number of model calls
* Transcript size

If your system uses external APIs or paid services, make sure the team understands the requirements and limitations.

Security

Do not commit API keys, tokens or other credentials to the repository.

Do not commit .env files containing secrets.

Use environment variables or another appropriate method for handling credentials.

Technology

There is no fixed technology stack for this challenge.

You can use whatever tools are appropriate for your solution, including:

* Traditional NLP
* LLMs
* Embeddings
* Vector databases
* Retrieval systems
* Local models
* External APIs
* Classical algorithms

You can also combine multiple approaches.

Using an LLM or another AI service is allowed, but the use of AI is not the main objective of the challenge.

The team should understand how the important parts of the system work and be able to explain the choices made during development.

What We Will Look At

The application will not be judged simply by the number of features it has.

The following areas are important.

Grounding

Can the system tell the difference between information that is actually present in the video and information that is not?

Retrieval

Can the system find the relevant part of a long transcript when a user asks about a specific topic?

Content Understanding

Does the application produce a useful structure from the transcript?

A generic summary of the entire video is not enough if the user still has difficulty finding specific information.

User Experience

Can someone use the application to learn from or investigate the video?

The interface does not need to be complicated. It should make the information easy to find and understand.

Reliability

How does the system behave when something goes wrong?

This includes missing transcripts, unavailable videos, processing failures and questions that cannot be answered from the source.

Engineering

The team should be able to explain the architecture, implementation and important trade-offs.

A simple solution that works reliably and can be explained clearly is better than a complicated system that the team cannot properly defend.

Implementation Decisions

There is no required architecture for this challenge.

Your team can decide:

* How transcripts are obtained
* How transcripts are cleaned
* How transcripts are divided into chunks or sections
* How topics and concepts are identified
* How information is stored
* How retrieval is performed
* Whether embeddings are used
* Whether an LLM is used
* How answers are generated
* How source information is shown to the user
* How relevance is determined
* How failures are handled

These decisions should be based on the requirements of your application rather than simply choosing technologies because they are popular.

Optional Features

The following features are optional.

They can improve the application if the core requirements are already working well:

* Timestamp-linked answers
* Automatic chapter detection
* Search across the transcript
* Source excerpts for answers
* Concept relationships or a knowledge graph
* Generated quizzes
* Learning checkpoints
* Flashcards
* Multilingual output
* Beginner and advanced explanations
* Comparing concepts discussed in different parts of the video

Do not sacrifice the core functionality to add optional features.

Acceptance Criteria

Before considering the project complete, verify that the application can do the following:

* [ ]	Accept a valid educational YouTube video URL
* [ ]	Validate the video input
* [ ]	Obtain and process a usable transcript or caption source
* [ ]	Identify major topics or sections
* [ ]	Identify important concepts and takeaways
* [ ]	Provide a way to explore the generated information
* [ ]	Allow users to ask questions about the video
* [ ]	Generate answers based on the video’s source material
* [ ]	Handle questions that cannot be answered from the source
* [ ]	Handle invalid or unavailable videos
* [ ]	Handle missing or unusable transcripts
* [ ]	Handle processing failures
* [ ]	Demonstrate the complete flow from video input to answer

Repository

The repository should contain enough information for another developer to set up and understand the project.

At minimum, include:

README.md
ARCHITECTURE.md
DECISIONS.md
TESTING.md

README.md

The README should explain:

* What the project does
* Main features
* Requirements
* Setup instructions
* Required environment variables
* How to start the application
* How to use the application

ARCHITECTURE.md

Document the main parts of the system.

Include:

* Major components
* Data flow
* Transcript processing
* Knowledge extraction
* Retrieval
* Question answering
* Important models and services
* Important technical decisions

An architecture diagram is recommended.

DECISIONS.md

Document the decisions that had a significant effect on the implementation.

For example:

* Why a particular retrieval method was selected
* Why a particular model was selected
* Why a particular chunking approach was used
* What alternatives were considered
* Why those alternatives were not used

The goal is to make the reasoning behind the implementation clear.

TESTING.md

Document how the application was tested.

Include:

* Main test cases
* Failure cases
* Edge cases
* Performance observations
* Known limitations

Demonstration

The final demonstration should show the application working end to end.

A useful demonstration could include:

1. Introduce the problem.
2. Provide an educational YouTube video.
3. Show the video being processed.
4. Show the topics or structure generated from the transcript.
5. Select a specific concept.
6. Find where that concept is discussed.
7. Ask a question whose answer is present in the video.
8. Show how the answer is supported by the source.
9. Ask a question that the video does not answer.
10. Show how the application handles that question.
11. Demonstrate one input or processing failure.
12. Explain the architecture and important technical decisions.

The demonstration should show the actual system rather than only screenshots or a prepared interface.

Event-Day Evaluation

During the final evaluation, you may be asked a question where the answer is buried somewhere in the video.

Your application should be able to show:

1. How the relevant information is found.
2. How that information is used to generate the answer.
3. Where the answer comes from in the source.
4. What happens when the source does not contain the answer.

The team should also be prepared to explain why the system can be trusted to stay within the video’s content.

Rules

* Build your own solution.
* AI-assisted development is allowed.
* Publicly available tools and resources may be used.
* Do not expose private credentials or secrets.
* Do not depend on a private service that will not be available during evaluation.
* Be prepared to explain the implementation.
* The team may be asked questions about any major part of the system.
* Core requirements take priority over optional features.

Final Checklist

Before submission, make sure:

* [ ]	The project runs from a clean setup.
* [ ]	YouTube video input works.
* [ ]	Transcript processing works.
* [ ]	Knowledge extraction works.
* [ ]	Content navigation works.
* [ ]	Question answering works.
* [ ]	Answers are grounded in the source.
* [ ]	Source information can be shown or verified.
* [ ]	Unsupported questions are handled clearly.
* [ ]	Invalid inputs are handled.
* [ ]	Missing transcripts are handled.
* [ ]	Processing failures are handled.
* [ ]	No credentials or secrets are committed.
* [ ]	Architecture documentation is complete.
* [ ]	Technical decisions are documented.
* [ ]	Testing is documented.
* [ ]	The final demonstration is ready.

INNOVEX: ARC Club