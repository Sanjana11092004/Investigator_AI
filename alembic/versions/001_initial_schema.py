"""Initial schema — matched to actual SDTM data and ClinicalTrials JSON.

Revision ID: 001
Revises:
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── ingested_documents ────────────────────────────────────────────────
    op.create_table(
        'ingested_documents',
        sa.Column('id',               postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('file_name',        sa.String(512),  nullable=False),
        sa.Column('file_path',        sa.Text(),       nullable=False),
        sa.Column('file_hash',        sa.String(64),   nullable=False),
        sa.Column('file_type',        sa.String(50),   nullable=False),
        sa.Column('file_size_bytes',  sa.Integer()),
        sa.Column('ingested_at',      sa.DateTime(),   nullable=False),
        sa.Column('status',           sa.String(50)),
        sa.Column('record_count',     sa.Integer()),
        sa.Column('error_message',    sa.Text()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_hash'),
    )
    op.create_index('ix_ingested_documents_file_hash', 'ingested_documents', ['file_hash'])

    # ── clinical_studies ──────────────────────────────────────────────────
    op.create_table(
        'clinical_studies',
        sa.Column('id',                    postgresql.UUID(as_uuid=True), nullable=False),
        # 1. Identification
        sa.Column('nct_id',                sa.String(20),   nullable=False),
        sa.Column('org_study_id',          sa.String(200)),
        sa.Column('organization_name',     sa.String(500)),
        sa.Column('brief_title',           sa.Text()),
        sa.Column('official_title',        sa.Text()),
        sa.Column('acronym',               sa.String(100)),
        # 2. Status
        sa.Column('overall_status',        sa.String(100)),
        sa.Column('start_date',            sa.String(50)),
        sa.Column('primary_completion_date', sa.String(50)),
        sa.Column('completion_date',       sa.String(50)),
        sa.Column('first_submitted_date',  sa.String(50)),
        sa.Column('results_posted_date',   sa.String(50)),
        sa.Column('last_update_date',      sa.String(50)),
        # 3. Sponsor
        sa.Column('lead_sponsor',          sa.String(500)),
        sa.Column('sponsor_class',         sa.String(100)),
        sa.Column('responsible_party',     sa.Text()),
        # 4. Description
        sa.Column('brief_summary',         sa.Text()),
        sa.Column('detailed_description',  sa.Text()),
        # 5. Conditions
        sa.Column('conditions',            sa.Text()),
        sa.Column('keywords',              sa.Text()),
        # 6. Design
        sa.Column('study_type',            sa.String(100)),
        sa.Column('observational_model',   sa.String(100)),
        sa.Column('time_perspective',      sa.String(100)),
        sa.Column('enrollment_count',      sa.Integer()),
        sa.Column('enrollment_type',       sa.String(50)),
        # 7. Interventions (JSON)
        sa.Column('interventions',         postgresql.JSON()),
        # 8. Outcomes (JSON)
        sa.Column('primary_outcomes',      postgresql.JSON()),
        sa.Column('secondary_outcomes',    postgresql.JSON()),
        # 9. Eligibility
        sa.Column('inclusion_criteria',    sa.Text()),
        sa.Column('exclusion_criteria',    sa.Text()),
        sa.Column('healthy_volunteers',    sa.String(50)),
        sa.Column('sex',                   sa.String(50)),
        sa.Column('minimum_age',           sa.String(50)),
        sa.Column('maximum_age',           sa.String(50)),
        sa.Column('std_age_categories',    sa.Text()),
        sa.Column('study_population',      sa.Text()),
        sa.Column('sampling_method',       sa.String(100)),
        # 10. Locations / Contacts (JSON)
        sa.Column('locations',             postgresql.JSON()),
        sa.Column('contacts',              postgresql.JSON()),
        # 11. Participant flow (JSON)
        sa.Column('participant_flow',      postgresql.JSON()),
        # 12. Baseline characteristics
        sa.Column('baseline_mean_age',     sa.Float()),
        sa.Column('baseline_sex_dist',     postgresql.JSON()),
        sa.Column('baseline_other',        postgresql.JSON()),
        # 13. Outcome results (JSON)
        sa.Column('outcome_results',       postgresql.JSON()),
        # 14. AE summary
        sa.Column('ae_serious_count',      sa.Integer()),
        sa.Column('ae_non_serious_count',  sa.Integer()),
        sa.Column('ae_population_at_risk', sa.Integer()),
        sa.Column('ae_summary',            postgresql.JSON()),
        # 15. References
        sa.Column('study_website',         sa.Text()),
        sa.Column('references',            postgresql.JSON()),
        # 16. Controlled vocabulary (JSON)
        sa.Column('mesh_conditions',       postgresql.JSON()),
        sa.Column('mesh_interventions',    postgresql.JSON()),
        sa.Column('condition_hierarchy',   postgresql.JSON()),
        sa.Column('intervention_hierarchy',postgresql.JSON()),
        # 17. Misc
        sa.Column('version_holder',        sa.String(200)),
        sa.Column('phase',                 sa.String(50)),
        sa.Column('raw_json',              sa.Text()),
        sa.Column('created_at',            sa.DateTime()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nct_id'),
    )
    op.create_index('ix_clinical_studies_nct_id', 'clinical_studies', ['nct_id'])
    op.create_index('ix_clinical_studies_status',  'clinical_studies', ['overall_status'])

    # ── patients ──────────────────────────────────────────────────────────
    op.create_table(
        'patients',
        sa.Column('id',         postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('study_id',   postgresql.UUID(as_uuid=True), nullable=True),
        # Core identifiers
        sa.Column('usubjid',    sa.String(100), nullable=False),
        sa.Column('subjid',     sa.String(50)),
        sa.Column('studyid',    sa.String(50)),
        sa.Column('domain',     sa.String(10)),
        # Dates
        sa.Column('rfstdtc',    sa.String(50)),
        sa.Column('rfendtc',    sa.String(50)),
        sa.Column('dmdtc',      sa.String(50)),
        sa.Column('dmdy',       sa.Integer()),
        # Site
        sa.Column('siteid',     sa.String(50)),
        sa.Column('country',    sa.String(100)),
        # Demographics
        sa.Column('age',        sa.Float()),
        sa.Column('ageu',       sa.String(20)),
        sa.Column('sex',        sa.String(20)),
        sa.Column('race',       sa.String(100)),
        sa.Column('ethnic',     sa.String(100)),
        # Arm
        sa.Column('armcd',      sa.String(50)),
        sa.Column('arm',        sa.String(200)),
        sa.Column('actarmcd',   sa.String(50)),
        sa.Column('actarm',     sa.String(200)),
        # Disease
        sa.Column('diagnosis',  sa.Text()),
        sa.Column('diagcd',     sa.String(50)),
        sa.Column('bmi',        sa.Float()),
        sa.Column('bmicat',     sa.String(50)),
        # Lifestyle
        sa.Column('smokestat',  sa.String(50)),
        sa.Column('alcoholuse', sa.String(50)),
        sa.Column('education',  sa.String(100)),
        # Death
        sa.Column('dthfl',      sa.String(10)),
        sa.Column('dthdtc',     sa.String(50)),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['study_id'], ['clinical_studies.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('usubjid'),
    )
    op.create_index('ix_patients_usubjid',  'patients', ['usubjid'])
    op.create_index('ix_patients_studyid',  'patients', ['studyid'])
    op.create_index('ix_patients_age',      'patients', ['age'])
    op.create_index('ix_patients_sex',      'patients', ['sex'])
    op.create_index('ix_patients_diagcd',   'patients', ['diagcd'])
    op.create_index('ix_patients_diagnosis','patients', ['diagnosis'])

    # ── adverse_events ────────────────────────────────────────────────────
    op.create_table(
        'adverse_events',
        sa.Column('id',         postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('usubjid',    sa.String(100)),
        sa.Column('studyid',    sa.String(50)),
        sa.Column('domain',     sa.String(10)),
        sa.Column('aeseq',      sa.Integer()),
        sa.Column('aeterm',     sa.String(500)),
        sa.Column('aedecod',    sa.String(500)),
        sa.Column('aebodsys',   sa.String(500)),
        sa.Column('aemeddra',   sa.String(50)),
        sa.Column('aestdtc',    sa.String(50)),
        sa.Column('aeendtc',    sa.String(50)),
        sa.Column('aedur',      sa.Integer()),
        sa.Column('aedy',       sa.Integer()),
        sa.Column('aesev',      sa.String(50)),
        sa.Column('aegrade',    sa.Integer()),
        sa.Column('aeout',      sa.String(100)),
        sa.Column('aerel',      sa.String(100)),
        sa.Column('aeserfl',    sa.String(10)),
        sa.Column('aesdth',     sa.String(10)),
        sa.Column('aeshosp',    sa.String(10)),
        sa.Column('aeslife',    sa.String(10)),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ae_patient_id', 'adverse_events', ['patient_id'])
    op.create_index('ix_ae_studyid',    'adverse_events', ['studyid'])
    op.create_index('ix_ae_aeserfl',    'adverse_events', ['aeserfl'])
    op.create_index('ix_ae_aedecod',    'adverse_events', ['aedecod'])
    op.create_index('ix_ae_aesev',      'adverse_events', ['aesev'])
    op.create_index('ix_ae_aegrade',    'adverse_events', ['aegrade'])
    op.create_index('ix_ae_aerel',      'adverse_events', ['aerel'])

    # ── lab_results ───────────────────────────────────────────────────────
    op.create_table(
        'lab_results',
        sa.Column('id',         postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('usubjid',    sa.String(100)),
        sa.Column('studyid',    sa.String(50)),
        sa.Column('domain',     sa.String(10)),
        sa.Column('lbseq',      sa.Integer()),
        sa.Column('visit',      sa.String(100)),
        sa.Column('visitnum',   sa.Float()),
        sa.Column('lbdtc',      sa.String(50)),
        sa.Column('lbdy',       sa.Integer()),
        sa.Column('lbtestcd',   sa.String(50)),
        sa.Column('lbtest',     sa.String(500)),
        sa.Column('lbstresn',   sa.Float()),
        sa.Column('lbstresu',   sa.String(100)),
        sa.Column('lbnrlo',     sa.Float()),
        sa.Column('lbnrhi',     sa.Float()),
        sa.Column('lbnrind',    sa.String(50)),
        sa.Column('lbclsig',    sa.String(10)),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lb_patient_id', 'lab_results', ['patient_id'])
    op.create_index('ix_lb_lbtestcd',   'lab_results', ['lbtestcd'])
    op.create_index('ix_lb_lbnrind',    'lab_results', ['lbnrind'])
    op.create_index('ix_lb_visitnum',   'lab_results', ['visitnum'])

    # ── concomitant_medications ───────────────────────────────────────────
    op.create_table(
        'concomitant_medications',
        sa.Column('id',         postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('usubjid',    sa.String(100)),
        sa.Column('studyid',    sa.String(50)),
        sa.Column('domain',     sa.String(10)),
        sa.Column('cmseq',      sa.Integer()),
        sa.Column('cmtrt',      sa.String(500)),
        sa.Column('cmdecod',    sa.String(500)),
        sa.Column('cmcat',      sa.String(200)),
        sa.Column('cmroute',    sa.String(100)),
        sa.Column('cmdose',     sa.String(100)),
        sa.Column('cmdosfrq',   sa.String(100)),
        sa.Column('cmstdtc',    sa.String(50)),
        sa.Column('cmendtc',    sa.String(50)),
        sa.Column('cmongo',     sa.String(10)),
        sa.Column('cmdy',       sa.Integer()),
        sa.Column('cmreas',     sa.Text()),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cm_patient_id', 'concomitant_medications', ['patient_id'])
    op.create_index('ix_cm_cmdecod',    'concomitant_medications', ['cmdecod'])

    # ── medical_histories ─────────────────────────────────────────────────
    op.create_table(
        'medical_histories',
        sa.Column('id',         postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('usubjid',    sa.String(100)),
        sa.Column('studyid',    sa.String(50)),
        sa.Column('domain',     sa.String(10)),
        sa.Column('mhseq',      sa.Integer()),
        sa.Column('mhterm',     sa.String(500)),
        sa.Column('mhdecod',    sa.String(500)),
        sa.Column('mhbodsys',   sa.String(500)),
        sa.Column('mhmeddra',   sa.String(50)),
        sa.Column('mhcat',      sa.String(200)),
        sa.Column('mhstdtc',    sa.String(50)),
        sa.Column('mhendtc',    sa.String(50)),
        sa.Column('mhongo',     sa.String(10)),
        sa.Column('mhdy',       sa.Integer()),
        sa.Column('mhsev',      sa.String(50)),
        sa.Column('created_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_mh_patient_id', 'medical_histories', ['patient_id'])
    op.create_index('ix_mh_mhdecod',    'medical_histories', ['mhdecod'])

    # ── investigation_sessions ────────────────────────────────────────────
    op.create_table(
        'investigation_sessions',
        sa.Column('id',                    postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_name',          sa.String(500), nullable=False),
        sa.Column('created_at',            sa.DateTime()),
        sa.Column('updated_at',            sa.DateTime()),
        sa.Column('active_study_id',       sa.String(100)),
        sa.Column('active_patient_id',     sa.String(100)),
        sa.Column('investigation_context', postgresql.JSON()),
        sa.Column('conversation_history',  postgresql.JSON()),
        sa.Column('session_summary',       sa.Text()),
        sa.Column('status',                sa.String(50)),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── audit_trail ───────────────────────────────────────────────────────
    op.create_table(
        'audit_trail',
        sa.Column('id',                postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id',        sa.String(100)),
        sa.Column('timestamp',         sa.DateTime(), nullable=False),
        sa.Column('action_type',       sa.String(100)),
        sa.Column('user_query',        sa.Text()),
        sa.Column('retrieval_type',    sa.String(50)),
        sa.Column('retrieved_sources', postgresql.JSON()),
        sa.Column('llm_response',      sa.Text()),
        sa.Column('entities_extracted',postgresql.JSON()),
        sa.Column('latency_ms',        sa.Float()),
        sa.Column('tokens_used',       postgresql.JSON()),
        sa.Column('error',             sa.Text()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_session_id', 'audit_trail', ['session_id'])
    op.create_index('ix_audit_timestamp',  'audit_trail', ['timestamp'])


def downgrade() -> None:
    op.drop_table('audit_trail')
    op.drop_table('investigation_sessions')
    op.drop_table('medical_histories')
    op.drop_table('concomitant_medications')
    op.drop_table('lab_results')
    op.drop_table('adverse_events')
    op.drop_table('patients')
    op.drop_table('clinical_studies')
    op.drop_table('ingested_documents')