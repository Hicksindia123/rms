import type { Page } from '@playwright/test';

export async function setupApiMocks(page: Page) {
  let hasDraft = false;
  let publishedVersion = 1;

  const sampleFormSnapshot = {
    form_code: 'S1_GATE_INWARD',
    name: 'Gate Inward & GS Creation',
    version: 1,
    status: 'PUBLISHED',
    fields: [
      {
        field_key: 'receiving_state',
        label: 'Receiving State / Destination Hub',
        control_type: 'text',
        sort_order: 10,
        required: true,
        is_core: true,
      },
      {
        field_key: 'delivery_mode',
        label: 'Mode of Delivery',
        control_type: 'dropdown',
        sort_order: 40,
        required: true,
        is_core: true,
        option_set_code: 'DELIVERY_MODE',
        options: [
          {
            code: 'COURIER',
            label: 'Courier / Parcel',
            sort_order: 10,
            allowed_status: 'YES',
          },
          {
            code: 'DIRECT_TRUCK',
            label: 'Direct Transport / Truck',
            sort_order: 20,
            allowed_status: 'CONDITIONAL',
            rule_text: 'Vehicle number and transporter details mandatory',
          },
          {
            code: 'CUSTOMER_HAND',
            label: 'Direct Handover',
            sort_order: 30,
            allowed_status: 'NO',
            rule_text: 'Customer direct handover not permitted at hub',
          },
        ],
      },
      {
        field_key: 'vehicle_no',
        label: 'Vehicle Registration Number',
        control_type: 'text',
        sort_order: 70,
        is_core: true,
        visible_when: { field: 'delivery_mode', op: 'eq', value: 'DIRECT_TRUCK' },
        required_when: { field: 'delivery_mode', op: 'eq', value: 'DIRECT_TRUCK' },
      },
      {
        field_key: 'transporter_name',
        label: 'Transporter / Fleet Name',
        control_type: 'text',
        sort_order: 80,
        is_core: true,
        visible_when: { field: 'delivery_mode', op: 'eq', value: 'DIRECT_TRUCK' },
        required_when: { field: 'delivery_mode', op: 'eq', value: 'DIRECT_TRUCK' },
      },
      {
        field_key: 'courier_name',
        label: 'Courier Company Name',
        control_type: 'text',
        sort_order: 50,
        is_core: true,
        visible_when: { field: 'delivery_mode', op: 'eq', value: 'COURIER' },
        required_when: { field: 'delivery_mode', op: 'eq', value: 'COURIER' },
      },
    ],
  };

  const formsList = [
    {
      id: 'f1',
      code: 'S1_GATE_INWARD',
      name: 'Gate Inward & GS Creation',
      category: 'GATE',
      is_active: true,
      has_published: true,
      latest_version: 1,
    },
    {
      id: 'f2',
      code: 'S1_UNBOXING',
      name: 'Unboxing & Box Verification',
      category: 'UNBOXING',
      is_active: true,
      has_published: true,
      latest_version: 1,
    },
  ];

  const optionSetsList = [
    {
      id: 'os1',
      code: 'DELIVERY_MODE',
      name: 'Delivery Mode',
      is_active: true,
      items_count: 3,
      items: [
        {
          id: 'i1',
          option_set_id: 'os1',
          code: 'COURIER',
          label: 'Courier / Parcel',
          sort_order: 10,
          is_active: true,
          allowed_status: 'YES',
          system_behavior: 'ALLOW',
        },
        {
          id: 'i2',
          option_set_id: 'os1',
          code: 'DIRECT_TRUCK',
          label: 'Direct Transport / Truck',
          sort_order: 20,
          is_active: true,
          allowed_status: 'CONDITIONAL',
          system_behavior: 'ALLOW',
          rule_text: 'Vehicle number and transporter details mandatory',
        },
        {
          id: 'i3',
          option_set_id: 'os1',
          code: 'CUSTOMER_HAND',
          label: 'Direct Handover',
          sort_order: 30,
          is_active: true,
          allowed_status: 'NO',
          system_behavior: 'ALLOW',
          rule_text: 'Customer direct handover not permitted at hub',
        },
      ],
    },
  ];

  await page.route('**/auth/v1/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'mock-jwt-token',
        token_type: 'bearer',
        expires_in: 3600,
        refresh_token: 'mock-refresh-token',
        user: {
          id: '00000000-0000-0000-0000-000000000001',
          aud: 'authenticated',
          role: 'authenticated',
          email: 'admin@rms.local',
          app_metadata: { provider: 'email' },
          user_metadata: {},
          created_at: new Date().toISOString(),
        },
      }),
    });
  });

  await page.route('**/api/v1/**', async (route) => {
    const url = route.request().url();
    if (url.endsWith('/me') || url.includes('/me?')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          profile: {
            id: '00000000-0000-0000-0000-000000000001',
            email: 'admin@rms.local',
            full_name: 'System Admin',
            is_super_admin: true,
          },
          roles: [{ code: 'SUPER_ADMIN', name: 'Super Administrator' }],
          permissions: [],
          step_codes: [],
        }),
      });
    } else if (url.includes('/config/forms/') && url.includes('/published')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sampleFormSnapshot),
      });
    } else if (url.includes('/config/forms/') && url.includes('/versions')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'v1',
            form_id: 'f1',
            version: 1,
            status: 'PUBLISHED',
            change_notes: 'Initial v1 seed',
            created_at: new Date().toISOString(),
          },
        ]),
      });
    } else if (url.includes('/config/forms')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(formsList),
      });
    } else if (url.includes('/config/options/sets/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(optionSetsList[0]),
      });
    } else if (url.includes('/config/options/sets')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(optionSetsList),
      });
    } else if (url.includes('/config/workflow/RMS_STANDARD/versions/')) {
      const isV2 = url.endsWith('/2') || url.includes('/versions/2');
      if (isV2 && hasDraft) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'w-draft-1',
            workflow_id: 'w1',
            code: 'RMS_STANDARD',
            name: 'RMS Standard Workflow',
            version_no: 2,
            status: 'DRAFT',
            stages: [
              {
                id: 'stg1',
                code: 'STAGE_1',
                label: 'Stage 1: Gate & Unboxing',
                sort_order: 10,
              },
            ],
            steps: [
              {
                id: 'stp1',
                stage_id: 'stg1',
                code: 'S1_GATE',
                label: 'S1 Gate Inward',
                sort_order: 10,
                is_active: true,
                sla_hours: 4,
                requires_approval: false,
                form_code: 'S1_GATE_INWARD',
                assignments: [
                  {
                    id: 'a1',
                    assignment_type: 'PERFORM',
                    role_code: 'GATE_INWARD',
                    role_id: null,
                    user_id: null,
                  },
                ],
              },
            ],
            transitions: [
              {
                id: 'tr1',
                from_step_id: 'stp1',
                from_step_code: 'S1_GATE',
                to_step_id: 'stp2',
                to_step_code: 'S1_UNBOX',
                condition: null,
                priority: 0,
                system_guards: ['G-01'],
              },
            ],
          }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'wv1',
            workflow_id: 'w1',
            code: 'RMS_STANDARD',
            name: 'RMS Standard Workflow',
            version_no: isV2 ? 2 : 1,
            status: 'PUBLISHED',
            stages: [
              {
                id: 'stg1',
                code: 'STAGE_1',
                label: 'Stage 1: Gate & Unboxing',
                sort_order: 10,
              },
              {
                id: 'stg2',
                code: 'STAGE_2',
                label: 'Stage 2: Technical Examination',
                sort_order: 20,
              },
            ],
            steps: [
              {
                id: 'stp1',
                stage_id: 'stg1',
                code: 'S1_GATE',
                label: 'Gate Inward & Entry',
                sort_order: 10,
                is_active: true,
                sla_hours: 4,
                requires_approval: false,
                form_code: 'S1_GATE_INWARD',
                assignments: [
                  {
                    id: 'a1',
                    assignment_type: 'PERFORM',
                    role_code: 'GATE_INWARD',
                    role_id: null,
                    user_id: null,
                  },
                ],
              },
              {
                id: 'stp2',
                stage_id: 'stg1',
                code: 'S1_UNBOX',
                label: 'Unboxing & Box Verification',
                sort_order: 20,
                is_active: true,
                sla_hours: 8,
                requires_approval: false,
                form_code: 'S1_UNBOXING',
                assignments: [],
              },
              {
                id: 'stp3',
                stage_id: 'stg2',
                code: 'S2_HANDOVER',
                label: 'Technical Handover',
                sort_order: 10,
                is_active: true,
                sla_hours: 4,
                requires_approval: false,
                form_code: 'S2_HANDOVER_INITIATE',
                assignments: [],
              },
            ],
            transitions: [
              {
                id: 'tr1',
                from_step_id: 'stp1',
                from_step_code: 'S1_GATE',
                to_step_id: 'stp2',
                to_step_code: 'S1_UNBOX',
                condition: null,
                priority: 0,
                system_guards: ['G-01'],
              },
              {
                id: 'tr2',
                from_step_id: 'stp2',
                from_step_code: 'S1_UNBOX',
                to_step_id: 'stp3',
                to_step_code: 'S2_HANDOVER',
                condition: null,
                priority: 0,
                system_guards: ['G-02'],
              },
            ],
          }),
        });
      }
    } else if (url.includes('/config/workflow/RMS_STANDARD/versions')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'wv1',
            workflow_id: 'w1',
            version_no: 1,
            status: 'PUBLISHED',
            change_notes: 'Initial v1 seed',
            created_at: new Date().toISOString(),
          },
        ]),
      });
    } else if (
      url.includes('/config/workflow/RMS_STANDARD/draft') &&
      route.request().method() === 'POST'
    ) {
      hasDraft = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'w-draft-1',
          workflow_id: 'w1',
          code: 'RMS_STANDARD',
          name: 'RMS Standard Workflow',
          version_no: 2,
          status: 'DRAFT',
          stages: [
            {
              id: 'stg1',
              code: 'STAGE_1',
              label: 'Stage 1: Gate & Unboxing',
              sort_order: 10,
            },
          ],
          steps: [
            {
              id: 'stp1',
              stage_id: 'stg1',
              code: 'S1_GATE',
              label: 'S1 Gate Inward',
              sort_order: 10,
              is_active: true,
              sla_hours: 4,
              requires_approval: false,
              form_code: 'S1_GATE_INWARD',
              assignments: [
                {
                  id: 'a1',
                  assignment_type: 'PERFORM',
                  role_code: 'GATE_INWARD',
                  role_id: null,
                  user_id: null,
                },
              ],
            },
          ],
          transitions: [],
        }),
      });
    } else if (
      url.includes('/config/workflow/') &&
      url.includes('/draft/publish') &&
      route.request().method() === 'POST'
    ) {
      hasDraft = false;
      publishedVersion = 2;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'w-pub-2',
          workflow_id: 'w1',
          code: 'RMS_STANDARD',
          name: 'RMS Standard Workflow',
          version_no: 2,
          status: 'PUBLISHED',
          change_notes: 'Updated step label',
          created_at: new Date().toISOString(),
        }),
      });
    } else if (
      url.includes('/config/workflow/') &&
      url.includes('/draft/step-label') &&
      route.request().method() === 'PUT'
    ) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      });
    } else if (url.includes('/config/workflow/RMS_STANDARD')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'w1',
          code: 'RMS_STANDARD',
          name: 'RMS Standard Workflow',
          is_active: true,
          latest_published_version: publishedVersion,
          has_draft: hasDraft,
          draft_version_no: hasDraft ? 2 : null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      });
    } else if (url.includes('/config/numbering/') && url.includes('/preview')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          next_numbers: ['GS-2425-00001', 'GS-2425-00002', 'GS-2425-00003'],
          series_code: 'GS_PROVISIONAL',
          current_counter: 0,
          reset_policy: 'FINANCIAL_YEAR',
          period_key: '2026-27',
          fy_string: '2627',
        }),
      });
    } else if (url.includes('/config/numbering')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'ns1',
            code: 'GS_PROVISIONAL',
            name: 'Gate Slip Provisional Number',
            prefix: 'GS',
            pattern: 'GS-{YY}{YY+1}-{NNNNN}',
            reset_policy: 'FINANCIAL_YEAR',
            fy_start_month: 4,
            fy_format: 'YY_YY_PLUS_ONE',
            start_value: 1,
            is_active: true,
            is_provisional_gs: true,
            max_used_counter: 0,
          },
        ]),
      });
    } else if (url.includes('/config/settings/branding/contrast-check')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contrast_ratio: 15.2,
          normal_text_aa: true,
          large_text_aa: true,
          normal_text_aaa: true,
        }),
      });
    } else if (url.includes('/config/settings')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 's1',
            key: 'branding_company_name',
            category: 'general',
            data_type: 'STRING',
            value: 'Exide Industries Limited',
            description: 'Company name shown in top navigation header',
            is_public: true,
          },
          {
            id: 's2',
            key: 'dec_01_gs_number_timing',
            category: 'provisional',
            data_type: 'STRING',
            value: 'GATE_ENTRY',
            description: 'DEC-01: Timing of Gate Slip (GS) Number generation',
            is_public: false,
          },
        ]),
      });
    } else if (url.includes('/config/templates') && url.includes('/sample')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          template_code: 'REPLACEMENT_SLIP',
          paper_size: 'A4',
          data_dictionary: [
            { field: 'slip_no', description: 'Slip reference number' },
            { field: 'product_name', description: 'Product name' },
          ],
          sample_data: {
            slip_no: 'RS-SAMPLE-001',
            is_sample_preview: true,
            items: [
              {
                line_no: 1,
                product_name: 'Battery 12V 100Ah',
                received_qty: 2,
                action_code: 'SCRAP',
              },
            ],
          },
        }),
      });
    } else if (url.includes('/config/templates')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 't1',
            code: 'REPLACEMENT_SLIP',
            name: 'Customer Replacement Slip',
            version_no: 1,
            status: 'PUBLISHED',
            layout: {
              paper_size: 'A4',
              orientation: 'portrait',
              header_title: 'REPLACEMENT SLIP',
              header_subtitle: 'Warehouse Inward & Replacement Acknowledgment',
              show_logo: true,
              signature_blocks: [{ label: 'Store Executive', role: 'STORE' }],
            },
          },
        ]),
      });
    } else if (url.includes('/config/system-guards')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            code: 'G-01',
            name: 'No Inward Without Slip / Missing Document Workflow',
            statement:
              'Material inward without physical document is blocked unless NO_DOCUMENT workflow is completed.',
            enforcement_layer: 'PostgreSQL + FastAPI',
            is_locked: true,
          },
          {
            code: 'G-18',
            name: 'Immutability of Form & Workflow Snapshots',
            statement:
              'Published form & workflow versions cannot be modified; any changes require a new version.',
            enforcement_layer: 'PostgreSQL trigger',
            is_locked: true,
          },
        ]),
      });
    } else if (url.includes('/config/history')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: 1,
              entity_type: 'WORKFLOW_DEFINITION',
              entity_id: 'RMS_STANDARD',
              action: 'PUBLISH',
              reason: 'Published RMS_STANDARD workflow v1',
              changed_at: new Date().toISOString(),
              before: null,
              after: { version: 1, status: 'PUBLISHED' },
              actor_email: 'admin@exide.local',
              actor_name: 'System Admin',
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    }
  });
}
