import { describe, it, expect, beforeEach } from 'vitest';
import { useHostContextStore } from '../stores/host-context-store';

describe('host-context-store', () => {
  beforeEach(() => {
    useHostContextStore.getState().clear();
  });

  it('should accept capabilities declaration', () => {
    useHostContextStore.getState().setCapabilities({
      host_type: 'lms',
      host_name: 'Maritime LMS',
      resources: ['current-page'],
      tools: [{ name: 'navigate', description: 'Nav', input_schema: {} }],
    });
    const caps = useHostContextStore.getState().capabilities;
    expect(caps?.host_type).toBe('lms');
    expect(caps?.tools).toHaveLength(1);
  });

  it('should update context', () => {
    const store = useHostContextStore.getState();
    store.updateContext({
      host_type: 'lms',
      page: { type: 'lesson', title: 'COLREGs' },
    });
    const ctx = useHostContextStore.getState().currentContext;
    expect(ctx?.page.type).toBe('lesson');
  });

  it('should format context for chat request', () => {
    const store = useHostContextStore.getState();
    store.updateContext({
      host_type: 'lms',
      page: { type: 'quiz', title: 'Test' },
      user_state: { scroll_percent: 50 },
    });
    const forRequest = useHostContextStore.getState().getContextForRequest();
    expect(forRequest).not.toBeNull();
    expect(forRequest?.host_type).toBe('lms');
    expect(forRequest?.page.type).toBe('quiz');
  });

  it('should sanitize control identifiers and secrets from chat request context', () => {
    const store = useHostContextStore.getState();
    store.updateContext({
      host_type: 'lms',
      page: {
        type: 'lesson',
        title: 'COLREGs',
        metadata: {
          safe: 'visible',
          connection_ref: 'conn-secret',
          page_id: 'page-secret',
          access_token: 'access-secret',
          wiii_connect: {
            provider_slug: 'facebook',
            status: 'connected',
            connection_id: 'conn-secret',
            page_id: 'page-secret',
          },
        },
      },
      selection: {
        text: 'visible selection',
        approval_token: 'approval-secret',
      },
      available_actions: [
        {
          action: 'safe.action',
          label: 'Safe action',
          input_schema: {
            properties: {
              message: { type: 'string' },
              connection_ref: { type: 'string' },
              image_base64: { type: 'string' },
            },
          },
        },
      ],
    });

    const current = useHostContextStore.getState().currentContext;
    expect(current?.page.metadata?.connection_ref).toBe('conn-secret');

    const forRequest = useHostContextStore.getState().getContextForRequest();
    const serialized = JSON.stringify(forRequest);
    expect(forRequest?.page.metadata?.safe).toBe('visible');
    expect(serialized).toContain('visible selection');
    expect(serialized).not.toContain('conn-secret');
    expect(serialized).not.toContain('page-secret');
    expect(serialized).not.toContain('access-secret');
    expect(serialized).not.toContain('approval-secret');
    expect(serialized).not.toContain('connection_ref');
    expect(serialized).not.toContain('connection_id');
    expect(serialized).not.toContain('page_id');
    expect(serialized).not.toContain('access_token');
    expect(serialized).not.toContain('approval_token');
    expect(serialized).not.toContain('image_base64');
  });

  it('should handle legacy wiii:page-context format', () => {
    const store = useHostContextStore.getState();
    store.setLegacyPageContext({
      page_type: 'lesson',
      page_title: 'Rule 14',
      course_name: 'COLREGs',
    });
    const ctx = useHostContextStore.getState().currentContext;
    expect(ctx?.host_type).toBe('lms');
    expect(ctx?.page.type).toBe('lesson');
    expect(ctx?.page.title).toBe('Rule 14');
  });

  it('should truncate long content snippets', () => {
    const store = useHostContextStore.getState();
    store.updateContext({
      host_type: 'lms',
      page: { type: 'lesson', title: 'T' },
      content: { snippet: 'A'.repeat(5000) },
    });
    const snippet = useHostContextStore.getState().currentContext?.content?.snippet;
    expect(snippet?.length).toBeLessThanOrEqual(2000);
  });

  it('should clear state', () => {
    const store = useHostContextStore.getState();
    store.updateContext({
      host_type: 'lms',
      page: { type: 'lesson', title: 'T' },
    });
    store.clear();
    expect(useHostContextStore.getState().currentContext).toBeNull();
    expect(useHostContextStore.getState().capabilities).toBeNull();
  });

  it('should preserve metadata in legacy conversion', () => {
    const store = useHostContextStore.getState();
    store.setLegacyPageContext({
      page_type: 'quiz',
      page_title: 'Test Quiz',
      course_name: 'Safety',
      quiz_question: 'Which vessel gives way?',
      quiz_options: ['Vessel A', 'Vessel B'],
    });
    const ctx = useHostContextStore.getState().currentContext;
    expect(ctx?.page.metadata?.course_name).toBe('Safety');
    expect(ctx?.page.metadata?.quiz_question).toBe('Which vessel gives way?');
  });

  it('should preserve future host metadata such as Pointy targets', () => {
    const store = useHostContextStore.getState();
    store.setLegacyPageContext({
      page_type: 'course_list',
      page_title: 'Courses',
      available_targets: [
        {
          id: 'browse-courses',
          selector: '[data-wiii-id="browse-courses"]',
          label: 'Browse courses',
        },
      ],
    });

    const ctx = useHostContextStore.getState().currentContext;
    expect(ctx?.page.metadata?.available_targets).toEqual([
      expect.objectContaining({
        id: 'browse-courses',
        selector: '[data-wiii-id="browse-courses"]',
      }),
    ]);
  });

  it('should block dangerous legacy metadata keys', () => {
    const store = useHostContextStore.getState();
    const legacy = {
      page_type: 'lesson',
      page_title: 'Safe page',
      constructor: 'bad',
      prototype: 'bad',
    } as Record<string, unknown>;
    Object.defineProperty(legacy, '__proto__', {
      value: { polluted: true },
      enumerable: true,
    });

    store.setLegacyPageContext(legacy);

    const metadata = useHostContextStore.getState().currentContext?.page.metadata;
    expect(Object.getPrototypeOf(metadata)).toBeNull();
    expect(metadata?.constructor).toBeUndefined();
    expect(metadata?.prototype).toBeUndefined();
    expect((metadata as Record<string, unknown>)?.__proto__).toBeUndefined();
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });

  it('should preserve connector and workspace overlays from legacy page context', () => {
    const store = useHostContextStore.getState();
    store.setLegacyPageContext({
      page_type: 'course_editor',
      page_title: 'Curriculum',
      connector_id: 'maritime-lms',
      host_user_id: 'teacher-1',
      host_workspace_id: 'org-1',
      host_organization_id: 'org-1',
    });

    const ctx = useHostContextStore.getState().currentContext;
    expect(ctx?.connector_id).toBe('maritime-lms');
    expect(ctx?.host_user_id).toBe('teacher-1');
    expect(ctx?.host_workspace_id).toBe('org-1');
    expect(ctx?.host_organization_id).toBe('org-1');
  });
});
