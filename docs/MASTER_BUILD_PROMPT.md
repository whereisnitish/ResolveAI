# MASTER BUILD PROMPT — RESOLVEAI

> Source brief for the project (originally drafted with ChatGPT, provided 2026-11-09).
> This is the authoritative product and engineering specification. Progress against it is
> tracked in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

You are acting as the **Principal Software Architect, Senior Full-Stack Engineer, AI Engineer, and Technical Lead** responsible for building a production-ready SaaS product called **ResolveAI**.

Your job is to architect, implement, test, and progressively deliver the complete application. Do not just explain what should be done. Work directly in the repository, create files, write code, run commands, execute tests, fix errors, and document decisions.

You have permission to make reasonable engineering decisions without asking me about every small detail. However, never perform destructive operations, expose secrets, or deploy to production without my explicit approval.

---

# 1. PRODUCT OVERVIEW

**Product:** ResolveAI  
**Tagline:** Your AI workforce for customer support.

ResolveAI is a commercial, multi-tenant, AI-powered customer support SaaS platform inspired by Intercom.

The platform enables SaaS companies, startups, and digital agencies to:

- Manage customer conversations through a shared inbox.
- Deploy AI support agents on their websites.
- Train AI agents using documents, websites, FAQs, and other knowledge sources.
- Automatically answer customer queries using RAG.
- Transfer conversations to human support agents when necessary.
- Manage customers, teams, workspaces, and conversations.
- Build automated support workflows.
- Monitor AI performance, usage, and analytics.
- Manage subscriptions and billing.

The product must support customers in **India and international markets** from day one.

This is intended to become a real commercial SaaS product, not a tutorial project or a prototype.

# 2. TECHNOLOGY STACK

Use the following architecture unless a genuine technical limitation requires a documented alternative.

## Frontend

- Next.js with App Router
- TypeScript
- Tailwind CSS
- shadcn/ui
- Lucide React
- React Hook Form
- Zod
- TanStack Query where appropriate
- Reusable, strongly typed components

## Backend

- Python
- Django
- Django REST Framework
- Django Channels for WebSockets
- PostgreSQL
- pgvector for vector search
- Redis
- Celery for background processing
- drf-spectacular for OpenAPI documentation

## AI infrastructure

- LangGraph for agent orchestration
- LangChain where useful
- Provider abstraction for LLMs
- Support OpenAI and Anthropic initially
- Design the architecture so additional providers can be added easily.
- RAG pipeline for knowledge retrieval
- Embedding provider abstraction
- Tool execution framework
- AI execution logging and tracing
- Human handoff when confidence is low or a customer requests a human

Do not tightly couple the application to one LLM provider.

## Infrastructure

- Docker
- Docker Compose for local development
- AWS-ready deployment architecture
- S3-compatible object storage
- Redis
- PostgreSQL with pgvector
- Nginx or an appropriate production ingress layer
- Environment-based configuration

## Payments

- Stripe for international customers
- Razorpay for Indian customers

Implement payment-provider abstractions so billing logic is not tied to one provider.

# 3. ARCHITECTURAL PRINCIPLES

Use a **modular monolith** initially. Do not introduce microservices unnecessarily.

Organize the backend by business domain.

Suggested structure:

```
resolveai/
├── backend/
│   ├── config/
│   ├── apps/
│   │   ├── accounts/
│   │   ├── organizations/
│   │   ├── workspaces/
│   │   ├── customers/
│   │   ├── conversations/
│   │   ├── messaging/
│   │   ├── ai_agents/
│   │   ├── knowledge/
│   │   ├── workflows/
│   │   ├── analytics/
│   │   ├── billing/
│   │   ├── integrations/
│   │   └── audit/
│   ├── common/
│   ├── services/
│   ├── tests/
│   ├── requirements/
│   └── manage.py
├── frontend/
├── widget/
├── infrastructure/
├── docs/
│   ├── architecture/
│   ├── api/
│   └── decisions/
├── docker-compose.yml
├── .env.example
└── README.md
```

You may improve this structure if needed, but preserve clear domain boundaries.

Important architectural rules:

1. Organization is the billing and ownership boundary.
2. Workspace is the support environment and data-isolation boundary.
3. An organization can have multiple workspaces.
4. An organization can have multiple users with different roles.
5. A user can belong to multiple organizations.
6. Every tenant-owned record must have proper organization/workspace ownership.
7. Enforce tenant isolation at the backend permission and query layers.
8. Never trust organization IDs or workspace IDs supplied by the frontend without authorization checks.
9. Consider PostgreSQL Row-Level Security as an additional defense-in-depth mechanism.
10. Use UUID primary keys for appropriate business entities.
11. Use database transactions for operations that must succeed or fail together.
12. Maintain audit logs for important security-sensitive actions.
13. Use asynchronous processing for expensive AI and background tasks.
14. Never expose API keys, private storage URLs, or internal system information to website visitors.

# 4. PRODUCT MODULES

Build the application as independently maintainable modules.

## A. Authentication and Accounts

Implement:

- User registration
- Login and logout
- Email verification
- Password reset
- Secure password hashing
- Session management
- Organization membership
- Invitations
- Role-based access control

Create a custom Django user model before the first migration.

Use secure, production-appropriate authentication. Prefer secure HttpOnly cookies for dashboard sessions when frontend and backend deployment architecture permits it.

## B. Organization and Workspace Management

Implement:

- Organization creation
- Organization settings
- Workspace creation
- Workspace switching
- Team member management
- Invitations
- Membership roles
- Permission checks

Suggested organization roles:

- Owner
- Admin
- Member
- Billing Admin

Suggested workspace roles:

- Admin
- Supervisor
- Agent
- Viewer

Define and enforce permissions centrally.

## C. Customer Management

Implement:

- Customer profiles
- Customer email and identity
- Customer metadata
- Conversation history
- Customer notes
- Customer tags
- Customer search
- Customer activity timeline

Support anonymous website visitors who may later become identified customers.

Do not assume that an anonymous visitor is the same identity as a registered user.

## D. Shared Inbox

Build a modern customer support inbox inspired by Intercom.

Features:

- Conversation list
- Real-time conversation updates
- Message history
- Incoming and outgoing messages
- Conversation assignment
- Team assignment
- Conversation status
- Priority
- Internal notes
- Tags
- Customer context
- Search and filters
- Read/unread state
- Attachments
- Human handoff
- AI-generated summaries

Conversation statuses:

- Open
- Pending
- Resolved
- Closed

Use Django Channels and Redis for real-time functionality.

## E. Website Chat Widget

Create an independently deployable website chat widget.

A customer should be able to install it using a simple script snippet on their website.

Example:

```html
<script
  src="https://cdn.resolveai.com/widget.js"
  data-workspace-id="PUBLIC_WORKSPACE_ID">
</script>
```

The widget should support:

- Floating chat launcher
- Expandable chat window
- Welcome message
- Conversation history
- Real-time messaging
- Typing indicators
- AI responses
- Human handoff
- Basic visitor identification
- Responsive UI
- Customizable branding

Security requirements:

- Never expose private API keys.
- Use short-lived, scoped visitor tokens.
- Validate workspace configuration.
- Apply rate limiting.
- Validate incoming messages.
- Prevent cross-workspace access.
- Apply appropriate CORS and origin restrictions.

The widget must communicate with the backend through public, narrowly scoped APIs.

## F. AI Agent Studio

This is one of the core differentiating modules.

Build an AI agent management interface.

Users should be able to:

- Create AI agents
- Name and describe agents
- Configure system instructions
- Select an LLM provider
- Configure model settings
- Select knowledge sources
- Configure response behavior
- Enable or disable agents
- Test agents in a playground
- Review execution history
- Configure human handoff rules

Use LangGraph for orchestration.

Design the AI execution lifecycle as:

1. Receive customer message.
2. Identify workspace and conversation context.
3. Load the correct AI agent configuration.
4. Retrieve relevant conversation history.
5. Retrieve relevant knowledge using RAG.
6. Determine whether tools or workflows are required.
7. Generate a response.
8. Validate the response and apply safety rules.
9. Decide whether human handoff is necessary.
10. Store the execution and token usage.
11. Deliver the response.
12. Record execution metrics.

Implement provider interfaces rather than hardcoding provider calls throughout the codebase.

## G. Knowledge Hub and RAG

Allow organizations to create knowledge bases.

Support:

- PDF uploads
- TXT uploads
- Markdown uploads
- Website URLs
- FAQs
- Manual text entries

Build an ingestion pipeline:

1. Receive source.
2. Validate file type and size.
3. Store files privately.
4. Extract content.
5. Clean and normalize text.
6. Split into chunks.
7. Generate embeddings.
8. Store chunks and embeddings in PostgreSQL using pgvector.
9. Track ingestion status.
10. Make sources available to AI agents.

Implement:

- Source management
- Ingestion status
- Re-indexing
- Deletion
- Retrieval testing
- Metadata filtering
- Workspace isolation

Run ingestion and embedding generation asynchronously using Celery.

Do not process large files synchronously inside HTTP requests.

## H. Human Handoff

The AI must be able to transfer conversations to human agents.

Implement:

- Customer requests human assistance
- AI cannot confidently answer
- Configurable escalation rules
- Agent assignment
- Handoff events
- Conversation state transitions
- AI pause/resume behavior
- Human takeover indicators

Do not allow the AI to continue replying while a human has explicitly taken control, unless the workspace configuration permits it.

## I. Workflow Automation

Build the foundation for workflow automation.

Examples:

- Automatically assign conversations.
- Send a welcome message.
- Escalate unresolved conversations.
- Apply tags based on intent.
- Trigger an action when a conversation is created.
- Trigger an action when a conversation is resolved.

Use a structured workflow definition and background execution system.

Do not implement arbitrary unsafe code execution.

## J. Analytics

Provide organization/workspace-level analytics:

- Total conversations
- Open conversations
- Resolved conversations
- AI resolution rate
- Human handoff rate
- Average response time
- Resolution time
- AI usage
- Token consumption
- Agent performance

Ensure analytics queries respect tenant boundaries.

## K. Billing and Usage

Implement:

- Subscription plans
- Trial support
- Usage tracking
- Usage ledger
- Billing history
- Subscription state
- Plan limits
- Payment provider abstraction
- Stripe integration foundation
- Razorpay integration foundation
- Webhook verification
- Idempotent webhook processing

Track usage for:

- AI conversations
- AI executions
- Token consumption
- Knowledge storage
- Team seats
- Other metered features as required

Do not trust frontend-supplied usage amounts.

Use an append-only usage ledger for auditable metering.

# 5. FRONTEND DESIGN REQUIREMENTS

The UI should be inspired by Intercom's modern SaaS experience.

Design direction:

- Clean and professional
- Minimal visual clutter
- Light theme as the initial default
- Neutral background colors
- Clear typography
- Subtle borders and shadows
- Consistent spacing
- Modern dashboard navigation
- Responsive layouts
- Excellent empty states
- Loading states and error states
- Accessible components

Use a consistent design system with reusable components.

Create:

### Public pages

- Landing page
- Pricing page
- Signup
- Login
- Forgot password
- Email verification

### Application pages

- Dashboard
- Inbox
- Conversation detail
- Customers
- Customer detail
- AI Agents
- Create AI Agent
- AI Agent detail
- AI Playground
- Knowledge Hub
- Knowledge Source detail
- Workflows
- Analytics
- Team
- Integrations
- Billing
- Settings

Suggested routes:

```
/
/pricing
/signup
/login
/forgot-password
/verify-email

/app
/app/inbox
/app/inbox/[conversationId]
/app/customers
/app/customers/[customerId]
/app/ai-agents
/app/ai-agents/new
/app/ai-agents/[agentId]
/app/knowledge
/app/knowledge/[sourceId]
/app/automation
/app/analytics
/app/team
/app/integrations
/app/billing
/app/settings
```

Build a polished, usable interface. Avoid placeholder-heavy screens that look complete but do nothing.

# 6. API DESIGN

Use versioned REST APIs:

/api/v1/

Organize endpoints by domain:

- /auth/
- /organizations/
- /workspaces/
- /customers/
- /conversations/
- /messages/
- /widget/
- /ai-agents/
- /knowledge/
- /workflows/
- /analytics/
- /billing/
- /integrations/

Requirements:

- Consistent response formats
- Input validation
- Pagination
- Filtering
- Search
- Proper HTTP status codes
- Authentication and permissions
- API documentation
- Rate limiting where appropriate
- Structured error handling

Use serializers for validation and keep business logic out of views.

Use service-layer functions for complex business operations.

# 7. DATABASE DESIGN

Design a normalized, scalable relational schema.

At minimum, evaluate and implement these entities:

- User
- Organization
- OrganizationMembership
- Workspace
- WorkspaceMembership
- Customer
- CustomerIdentity
- Conversation
- Message
- ConversationEvent
- ConversationAssignment
- Attachment
- AIAgent
- KnowledgeSource
- KnowledgeChunk
- AIExecution
- ToolExecution
- Workflow
- WorkflowExecution
- Plan
- Subscription
- UsageLedger
- Invoice
- Integration
- AuditLog
- WebhookEvent

Add indexes, constraints, unique constraints, and appropriate deletion behavior.

Avoid unnecessary denormalization.

Document important relationships and design decisions.

# 8. SECURITY AND PRODUCTION REQUIREMENTS

Treat security as a first-class requirement.

Implement:

- Tenant isolation
- Role-based access control
- Secure authentication
- CSRF protection
- CORS restrictions
- Input validation
- File upload validation
- Rate limiting
- Secure secrets management
- Webhook signature verification
- Audit logging
- Secure error responses
- Database transaction handling
- Protection against IDOR
- Protection against cross-tenant data access

Never:

- Commit secrets.
- Hardcode API keys.
- Trust frontend permissions.
- Expose internal prompts or private agent configuration to visitors.
- Allow users to access another organization's data.
- Store passwords in plain text.
- Execute arbitrary user-provided code.

Use environment variables for configuration and maintain a complete `.env.example` with placeholder values only.

# 9. TESTING AND QUALITY

Write meaningful automated tests.

Backend:

- Model tests
- Serializer tests
- API tests
- Permission tests
- Tenant isolation tests
- Authentication tests
- Service-layer tests
- Celery task tests
- Webhook tests

Frontend:

- Component tests where useful
- Form validation
- Authentication flows
- Important user journeys

Critical security tests:

1. User from Organization A cannot access Organization B data.
2. User cannot access an unauthorized workspace by guessing its UUID.
3. Inactive members cannot access workspace data.
4. Widget tokens cannot access another workspace.
5. Anonymous visitors cannot call privileged dashboard APIs.
6. Duplicate webhook events do not process payments or usage twice.
7. AI cannot send a response after a human has taken control, unless explicitly configured.

Run tests and fix failures before marking features complete.

Use linting, formatting, and static checks.

# 10. DEVELOPMENT EXECUTION STRATEGY

Do not attempt to build the entire platform as one enormous, untested code dump.

Work in implementation phases, but continue working autonomously through each phase.

## Phase 0 — Repository inspection and planning

- Inspect the existing repository.
- Identify existing code and dependencies.
- Do not overwrite existing work without understanding it.
- Create architecture documentation.
- Create implementation roadmap.
- Create `.env.example`.
- Establish coding conventions.

## Phase 1 — Foundation

Implement:

- Django project setup
- Next.js project setup
- Docker Compose
- PostgreSQL with pgvector
- Redis
- Celery
- Custom user model
- Organization model
- Workspace model
- Membership models
- Authentication
- Registration flow
- Initial migrations
- Tenant permission framework
- API documentation
- Initial automated tests

**Foundation acceptance criteria:**

- The application starts locally.
- A user can register.
- Registration creates an organization and default workspace.
- The registering user becomes the organization owner.
- The user can authenticate.
- The user can access only authorized organization/workspace data.
- Tests verify tenant isolation.

## Phase 2 — Core customer support

Implement:

- Customer management
- Conversations
- Messages
- Assignments
- Shared inbox
- Real-time updates
- Website widget foundation

## Phase 3 — AI platform

Implement:

- AI agent management
- LLM provider abstraction
- LangGraph orchestration
- Knowledge ingestion
- Embeddings
- RAG retrieval
- AI execution logs
- Playground
- Human handoff

## Phase 4 — Business features

Implement:

- Workflow automation
- Analytics
- Team management
- Integrations
- Usage tracking
- Billing foundations

## Phase 5 — Commercial readiness

Implement:

- Production configuration
- Security hardening
- Performance optimization
- Monitoring
- Logging
- Error tracking
- Backup strategy documentation
- Deployment documentation
- End-to-end tests

# 11. WORKING RULES — VERY IMPORTANT

You are expected to work as an autonomous engineering agent.

Follow these rules:

1. First inspect the existing repository and available development environment.
2. If the repository is empty, initialize the project.
3. If an application already exists, preserve and extend it.
4. Do not just provide instructions. Create and edit actual files.
5. Do not stop after generating a plan.
6. Do not ask for confirmation for ordinary technical decisions.
7. Make sensible defaults and document significant architectural decisions.
8. Install dependencies only when needed.
9. Run commands and inspect their actual output.
10. Fix errors rather than leaving broken code.
11. Write tests alongside implementation.
12. Keep the README updated.
13. Keep `.env.example` updated.
14. Never commit real credentials.
15. Never deploy to production without my approval.
16. Do not claim that something works unless you have verified it.
17. If an external API key is missing, implement the integration interface, provide a mock/local development mode, and document which environment variable is needed.
18. Avoid unnecessary abstractions and premature microservices.
19. Use type hints in Python and strict TypeScript where practical.
20. Prefer maintainable, readable code over clever shortcuts.

## Progress tracking

Create:

`docs/IMPLEMENTATION_STATUS.md`

For every module, track:

- Not started
- In progress
- Implemented
- Tested
- Production ready

Also maintain:

`docs/architecture/ARCHITECTURE.md`

`docs/architecture/DATABASE.md`

`docs/architecture/SECURITY.md`

`docs/decisions/`

For important architecture choices, create short ADR documents explaining the decision and its trade-offs.

At the end of each implementation phase:

- Summarize files created or modified.
- List implemented functionality.
- Report commands executed.
- Report test results.
- Identify unresolved issues.
- State the next implementation milestone.

# 12. YOUR FIRST TASK — START BUILDING NOW

Start with Phase 0 and Phase 1.

Do the following in order:

1. Inspect the repository.
2. Determine whether the frontend/backend already exist.
3. Establish the project structure.
4. Initialize the Django backend.
5. Initialize the Next.js frontend if it does not already exist.
6. Configure PostgreSQL, pgvector, Redis, and Celery through Docker Compose.
7. Implement the custom user model.
8. Implement organization and workspace models.
9. Implement membership and permission models.
10. Implement registration and authentication.
11. Implement tenant-scoped API permissions.
12. Create and run migrations.
13. Write automated tests.
14. Run the tests and fix failures.
15. Create/update all relevant documentation.

Do not build superficial versions of all modules just to make the project appear complete.

Prioritize a solid, tested foundation that can support the full commercial product.

**Begin by inspecting the repository and then immediately start implementing. Do not respond with only a plan.**
