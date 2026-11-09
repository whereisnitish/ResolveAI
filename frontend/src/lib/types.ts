// Mirrors backend serializers (see docs/api/openapi.yaml).

export type OrganizationRole = "owner" | "admin" | "member" | "billing_admin";
export type WorkspaceRole = "admin" | "supervisor" | "agent" | "viewer";

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  email_verified: boolean;
  date_joined: string;
}

export interface MeOrganization {
  id: string;
  name: string;
  slug: string;
  role: OrganizationRole;
  permissions: string[];
}

export interface MeWorkspace {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  is_default: boolean;
  role: WorkspaceRole;
  permissions: string[];
}

export interface Me {
  user: User;
  organizations: MeOrganization[];
  workspaces: MeWorkspace[];
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  country: string;
  role: OrganizationRole | null;
  created_at: string;
}

export interface Workspace {
  id: string;
  organization: string;
  name: string;
  slug: string;
  public_id: string;
  timezone: string;
  is_default: boolean;
  role: WorkspaceRole | null;
  created_at: string;
}

export interface MemberUser {
  id: string;
  email: string;
  full_name: string;
}

export interface OrganizationMembership {
  id: string;
  user: MemberUser;
  role: OrganizationRole;
  is_active: boolean;
  created_at: string;
}

export interface WorkspaceMembership {
  id: string;
  user: MemberUser;
  role: WorkspaceRole;
  is_active: boolean;
  created_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: OrganizationRole;
  workspace: string | null;
  workspace_role: WorkspaceRole | "";
  status: "pending" | "accepted" | "revoked";
  expires_at: string;
  is_expired: boolean;
  invited_by: MemberUser | null;
  created_at: string;
}

export interface InvitationPreview {
  organization_name: string;
  email: string;
  role: OrganizationRole;
  invited_by_name: string;
  expires_at: string;
  account_exists: boolean;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  actor_email: string;
  workspace_id: string | null;
  target_type: string;
  target_id: string;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export const ORG_ROLE_LABELS: Record<OrganizationRole, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  billing_admin: "Billing Admin",
};

export const WORKSPACE_ROLE_LABELS: Record<WorkspaceRole, string> = {
  admin: "Admin",
  supervisor: "Supervisor",
  agent: "Agent",
  viewer: "Viewer",
};

// ---------------------------------------------------------------------------
// Phase 2: customers, conversations, widget
// ---------------------------------------------------------------------------
export type ConversationStatus = "open" | "pending" | "resolved" | "closed";
export type ConversationPriority = "low" | "normal" | "high" | "urgent";
export type ActorType = "customer" | "agent" | "ai" | "system";

export interface Tag {
  id: string;
  name: string;
  color: string;
}

export interface TeamMember {
  id: string;
  full_name: string;
  email: string;
}

export interface Team {
  id: string;
  name: string;
  members: TeamMember[];
  created_at: string;
}

export interface Customer {
  id: string;
  display_name: string;
  name: string;
  email: string;
  phone: string;
  external_id: string;
  attributes: Record<string, string | number | boolean | null>;
  tags: Tag[];
  is_anonymous: boolean;
  identified_at: string | null;
  last_seen_at: string | null;
  last_seen_url: string;
  user_agent: string;
  conversation_count?: number;
  created_at: string;
}

export interface CustomerNote {
  id: string;
  body: string;
  author: { id: string; full_name: string; email: string } | null;
  created_at: string;
}

export interface TimelineItem {
  id: string;
  kind: string;
  title: string;
  detail: string;
  conversation_id: string | null;
  actor_name: string;
  at: string;
}

export interface Person {
  id: string;
  name: string;
  email: string;
}

export interface Conversation {
  id: string;
  number: number;
  subject: string;
  channel: "widget" | "dashboard";
  status: ConversationStatus;
  priority: ConversationPriority;
  customer: { id: string; display_name: string; email: string; is_anonymous: boolean };
  assignee: Person | null;
  team: { id: string; name: string } | null;
  tags: Tag[];
  last_message_at: string;
  last_message_preview: string;
  last_message_author_type: ActorType | "";
  last_customer_message_at: string | null;
  first_response_at: string | null;
  resolved_at: string | null;
  is_unread: boolean;
  ai_state: "active" | "paused" | "handed_off";
  ai_summary: string;
  ai_summary_at: string | null;
  human_takeover_at: string | null;
  created_at: string;
}

export interface MessageAttachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
}

export interface Message {
  id: string;
  kind: "reply" | "note";
  author_type: ActorType;
  author: Person | null;
  body: string;
  attachments: MessageAttachment[];
  created_at: string;
}

export interface CursorPage<T> {
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface ConversationEvent {
  id: string;
  type: string;
  actor_type: ActorType;
  actor: Person | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface ConversationCounts {
  mine: number;
  unassigned: number;
  all: number;
  by_status: Record<ConversationStatus, number>;
  by_team: Record<string, number>;
}

export interface Assignee {
  id: string;
  full_name: string;
  email: string;
}

export interface WidgetSettings {
  enabled: boolean;
  allowed_origins: string[];
  brand_color: string;
  team_name: string;
  welcome_message: string;
  launcher_position: "right" | "left";
  collect_email: boolean;
  updated_at: string;
}

export const STATUS_LABELS: Record<ConversationStatus, string> = {
  open: "Open",
  pending: "Pending",
  resolved: "Resolved",
  closed: "Closed",
};

export const PRIORITY_LABELS: Record<ConversationPriority, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};
