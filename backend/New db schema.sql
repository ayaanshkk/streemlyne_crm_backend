-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE StreemLyne_MT.Case_Documents (
  id integer NOT NULL DEFAULT nextval('"StreemLyne_MT"."Case_Documents_id_seq"'::regclass),
  opportunity_id smallint NOT NULL,
  client_id smallint NOT NULL,
  tenant_id smallint NOT NULL,
  uploaded_by character varying NOT NULL,
  document_type character varying,
  file_name character varying NOT NULL,
  blob_url text NOT NULL,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT Case_Documents_pkey PRIMARY KEY (id),
  CONSTRAINT fk_case_documents_opportunity FOREIGN KEY (opportunity_id) REFERENCES StreemLyne_MT.Opportunity_Details(opportunity_id),
  CONSTRAINT fk_case_documents_client FOREIGN KEY (client_id) REFERENCES StreemLyne_MT.Client_Master(client_id)
);
CREATE TABLE StreemLyne_MT.Client_Interactions (
  interaction_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  client_id smallint NOT NULL,
  contact_date date NOT NULL,
  contact_method smallint NOT NULL,
  notes character varying,
  next_steps character varying,
  reminder_date date,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT Client_Interactions_pkey PRIMARY KEY (interaction_id),
  CONSTRAINT Client_Interactions_client_id_fkey FOREIGN KEY (client_id) REFERENCES StreemLyne_MT.Client_Master(client_id)
);
CREATE TABLE StreemLyne_MT.Client_Master (
  client_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  tenant_id smallint NOT NULL,
  client_company_name character varying NOT NULL,
  client_contact_name character varying,
  address character varying,
  country_id smallint,
  post_code character varying,
  client_phone character varying,
  client_email character varying,
  client_website character varying,
  default_currency_id smallint,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT Client_Master_pkey PRIMARY KEY (client_id),
  CONSTRAINT Client_Master_country_id_fkey FOREIGN KEY (country_id) REFERENCES StreemLyne_MT.Country_Master(country_id),
  CONSTRAINT Client_Master_default_currency_id_fkey FOREIGN KEY (default_currency_id) REFERENCES StreemLyne_MT.Currency_Master(currency_id),
  CONSTRAINT Client_Master_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES StreemLyne_MT.Tenant_Master(tenant_id)
);
CREATE TABLE StreemLyne_MT.Country_Master (
  country_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  country_name character varying NOT NULL UNIQUE,
  country_isd_code character varying NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT Country_Master_pkey PRIMARY KEY (country_id)
);
CREATE TABLE StreemLyne_MT.Currency_Master (
  currency_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  currency_name character varying,
  currency_code character varying,
  created_at timestamp without time zone,
  CONSTRAINT Currency_Master_pkey PRIMARY KEY (currency_id)
);
CREATE TABLE StreemLyne_MT.Customer_Auth (
  customer_user_id integer NOT NULL DEFAULT nextval('"StreemLyne_MT"."Customer_Auth_customer_user_id_seq"'::regclass),
  client_id smallint NOT NULL,
  tenant_id smallint NOT NULL,
  email character varying NOT NULL UNIQUE,
  password_hash text NOT NULL,
  is_active boolean DEFAULT true,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT Customer_Auth_pkey PRIMARY KEY (customer_user_id),
  CONSTRAINT Customer_Auth_client_id_fkey FOREIGN KEY (client_id) REFERENCES StreemLyne_MT.Client_Master(client_id),
  CONSTRAINT Customer_Auth_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES StreemLyne_MT.Tenant_Master(tenant_id)
);
CREATE TABLE StreemLyne_MT.Customer_Documents (
  id integer NOT NULL DEFAULT nextval('"StreemLyne_MT"."Customer_Documents_id_seq"'::regclass),
  client_id smallint NOT NULL,
  opportunity_id smallint,
  file_url text NOT NULL,
  file_name text NOT NULL,
  uploaded_at timestamp without time zone DEFAULT now(),
  CONSTRAINT Customer_Documents_pkey PRIMARY KEY (id)
);
CREATE TABLE StreemLyne_MT.Customer_Password_Reset (
  id integer NOT NULL DEFAULT nextval('"StreemLyne_MT"."Customer_Password_Reset_id_seq"'::regclass),
  customer_user_id integer,
  token text NOT NULL,
  expires_at timestamp without time zone NOT NULL,
  used boolean DEFAULT false,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT Customer_Password_Reset_pkey PRIMARY KEY (id),
  CONSTRAINT Customer_Password_Reset_customer_user_id_fkey FOREIGN KEY (customer_user_id) REFERENCES StreemLyne_MT.Customer_Auth(customer_user_id)
);
CREATE TABLE StreemLyne_MT.Designation_Master (
  designation_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  designation_description character varying NOT NULL UNIQUE,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT Designation_Master_pkey PRIMARY KEY (designation_id)
);
CREATE TABLE StreemLyne_MT.Employee_Master (
  employee_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  tenant_id bigint NOT NULL,
  employee_name character varying NOT NULL,
  employee_designation_id smallint,
  phone character varying,
  email character varying UNIQUE,
  date_of_birth date,
  date_of_joining date,
  id_type character varying,
  id_number character varying,
  role_ids character varying,
  created_on timestamp without time zone DEFAULT now(),
  updated_on timestamp without time zone,
  commission_percentage real,
  CONSTRAINT Employee_Master_pkey PRIMARY KEY (employee_id),
  CONSTRAINT Employee_Master_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES StreemLyne_MT.Tenant_Master(tenant_id),
  CONSTRAINT Employee_Master_employee_designation_id_fkey FOREIGN KEY (employee_designation_id) REFERENCES StreemLyne_MT.Designation_Master(designation_id)
);
CREATE TABLE StreemLyne_MT.Energy_Contract_Master (
  energy_contract_master_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  project_id smallint,
  employee_id smallint NOT NULL,
  supplier_id smallint NOT NULL,
  contract_start_date date NOT NULL,
  contract_end_date date NOT NULL,
  terms_of_sale character varying NOT NULL,
  service_id smallint NOT NULL,
  unit_rate real NOT NULL,
  currency_id smallint,
  document_details character varying,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone,
  mpan_number character varying,
  CONSTRAINT Energy_Contract_Master_pkey PRIMARY KEY (energy_contract_master_id),
  CONSTRAINT Energy_Contract_Master_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES StreemLyne_MT.Employee_Master(employee_id),
  CONSTRAINT Energy_Contract_Master_service_id_fkey FOREIGN KEY (service_id) REFERENCES StreemLyne_MT.Services_Master(service_id),
  CONSTRAINT Energy_Contract_Master_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES StreemLyne_MT.Currency_Master(currency_id),
  CONSTRAINT Energy_Contract_Master_project_id_fkey FOREIGN KEY (project_id) REFERENCES StreemLyne_MT.Project_Details(project_id)
);
CREATE TABLE StreemLyne_MT.Invoice_Details (
  invoice_details_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL,
  invoice_id smallint NOT NULL,
  service_id smallint NOT NULL,
  quantity real NOT NULL,
  uom_id smallint NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp without time zone,
  CONSTRAINT Invoice_Details_pkey PRIMARY KEY (invoice_details_id),
  CONSTRAINT invoice_details_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES StreemLyne_MT.Invoice_Master(invoice_id),
  CONSTRAINT invoice_details_service_id_fkey FOREIGN KEY (service_id) REFERENCES StreemLyne_MT.Services_Master(service_id),
  CONSTRAINT invoice_details_uom_id_fkey FOREIGN KEY (uom_id) REFERENCES StreemLyne_MT.UOM_Master(uom_id)
);
CREATE TABLE StreemLyne_MT.Invoice_Master (
  invoice_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL,
  client_id smallint,
  project_id smallint,
  proposal_id smallint,
  invoice_number character varying NOT NULL,
  billing_remarks character varying,
  sub_total real,
  currency_id smallint,
  tax_id smallint NOT NULL,
  total_amount real NOT NULL,
  discount_percent real,
  discount_amount real,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp without time zone,
  CONSTRAINT Invoice_Master_pkey PRIMARY KEY (invoice_id),
  CONSTRAINT proposal_master_client_id_fkey FOREIGN KEY (client_id) REFERENCES StreemLyne_MT.Client_Master(client_id),
  CONSTRAINT proposal_master_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES StreemLyne_MT.Currency_Master(currency_id),
  CONSTRAINT Invoice_Master_project_id_fkey FOREIGN KEY (project_id) REFERENCES StreemLyne_MT.Project_Details(project_id),
  CONSTRAINT Invoice_Master_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES StreemLyne_MT.Proposal_Master(proposal_id)
);
CREATE TABLE StreemLyne_MT.Module_Master (
  module_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  module_code character varying NOT NULL UNIQUE,
  module_name character varying NOT NULL UNIQUE,
  description character varying,
  is_core boolean NOT NULL,
  is_active boolean NOT NULL,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone,
  CONSTRAINT Module_Master_pkey PRIMARY KEY (module_id)
);
CREATE TABLE StreemLyne_MT.Opportunity_Details (
  opportunity_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  client_id smallint,
  opportunity_title character varying NOT NULL,
  opportunity_description character varying,
  opportunity_date date,
  opportunity_owner_employee_id smallint,
  stage_id smallint NOT NULL,
  opportunity_value smallint,
  currency_id smallint,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  Misc_Col1 character varying,
  tenant_id bigint,
  mpan_mpr character varying,
  business_name character varying,
  contact_person character varying,
  tel_number character varying,
  email character varying,
  start_date date,
  end_date date,
  deleted_at timestamp without time zone,
  service_id smallint,
  assigned_to_employee_id integer,
  CONSTRAINT Opportunity_Details_pkey PRIMARY KEY (opportunity_id),
  CONSTRAINT Opportunity_Details_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES StreemLyne_MT.Currency_Master(currency_id),
  CONSTRAINT Opportunity_Details_opportunity_owner_employee_id_fkey FOREIGN KEY (opportunity_owner_employee_id) REFERENCES StreemLyne_MT.Employee_Master(employee_id),
  CONSTRAINT Opportunity_Details_client_id_fkey FOREIGN KEY (client_id) REFERENCES StreemLyne_MT.Client_Master(client_id),
  CONSTRAINT fk_opportunity_tenant FOREIGN KEY (tenant_id) REFERENCES StreemLyne_MT.Tenant_Master(tenant_id),
  CONSTRAINT fk_assigned_employee FOREIGN KEY (assigned_to_employee_id) REFERENCES StreemLyne_MT.Employee_Master(employee_id)
);
CREATE TABLE StreemLyne_MT.Permission_Catalog (
  permission_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  permission_code character varying NOT NULL UNIQUE,
  description character varying,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT Permission_Catalog_pkey PRIMARY KEY (permission_id)
);
CREATE TABLE StreemLyne_MT.Project_Details (
  project_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  client_id smallint NOT NULL,
  opportunity_id smallint NOT NULL,
  project_title character varying NOT NULL,
  project_description character varying,
  start_date date NOT NULL,
  end_date date,
  employee_id smallint NOT NULL,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone,
  address character varying,
  Misc_Col1 character varying,
  Misc_Col2 integer,
  CONSTRAINT Project_Details_pkey PRIMARY KEY (project_id),
  CONSTRAINT Project_Details_opportunity_id_fkey FOREIGN KEY (opportunity_id) REFERENCES StreemLyne_MT.Opportunity_Details(opportunity_id),
  CONSTRAINT Project_Details_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES StreemLyne_MT.Employee_Master(employee_id)
);
CREATE TABLE StreemLyne_MT.Proposal_Details (
  proposal_details_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  proposal_id smallint NOT NULL,
  service_id smallint NOT NULL,
  quantity real NOT NULL,
  uom_id smallint NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp without time zone,
  CONSTRAINT Proposal_Details_pkey PRIMARY KEY (proposal_details_id),
  CONSTRAINT Proposal_Details_uom_id_fkey FOREIGN KEY (uom_id) REFERENCES StreemLyne_MT.UOM_Master(uom_id),
  CONSTRAINT Proposal_Details_proposal_id_fkey FOREIGN KEY (proposal_id) REFERENCES StreemLyne_MT.Proposal_Master(proposal_id),
  CONSTRAINT Proposal_Details_service_id_fkey FOREIGN KEY (service_id) REFERENCES StreemLyne_MT.Services_Master(service_id)
);
CREATE TABLE StreemLyne_MT.Proposal_Master (
  proposal_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  client_id smallint,
  project_id smallint,
  sub_total real,
  currency_id smallint,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp without time zone,
  tax_id smallint NOT NULL,
  total_amount real NOT NULL,
  discount_percent real,
  discount_amount real,
  CONSTRAINT Proposal_Master_pkey PRIMARY KEY (proposal_id),
  CONSTRAINT Proposal_Master_client_id_fkey FOREIGN KEY (client_id) REFERENCES StreemLyne_MT.Client_Master(client_id),
  CONSTRAINT Proposal_Master_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES StreemLyne_MT.Currency_Master(currency_id)
);
CREATE TABLE StreemLyne_MT.Role_Master (
  role_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  role_name character varying NOT NULL UNIQUE,
  role_description character varying,
  is_system boolean NOT NULL,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT Role_Master_pkey PRIMARY KEY (role_id)
);
CREATE TABLE StreemLyne_MT.Role_Permission_Mapping (
  role_permission_mapping_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  role_id smallint NOT NULL,
  permission_id smallint NOT NULL,
  created_at timestamp without time zone DEFAULT now(),
  edited_at date,
  CONSTRAINT Role_Permission_Mapping_pkey PRIMARY KEY (role_permission_mapping_id),
  CONSTRAINT Role_Permission_Mapping_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES StreemLyne_MT.Permission_Catalog(permission_id),
  CONSTRAINT Role_Permission_Mapping_role_id_fkey FOREIGN KEY (role_id) REFERENCES StreemLyne_MT.Role_Master(role_id)
);
CREATE TABLE StreemLyne_MT.Services_Master (
  service_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  tenant_id smallint NOT NULL,
  service_title character varying NOT NULL,
  service_description character varying,
  service_rate real,
  currency_id smallint,
  supplier_id smallint,
  date_from date,
  date_to date,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  service_code character varying NOT NULL,
  CONSTRAINT Services_Master_pkey PRIMARY KEY (service_id),
  CONSTRAINT Services_Master_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES StreemLyne_MT.Tenant_Master(tenant_id),
  CONSTRAINT Services_Master_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES StreemLyne_MT.Currency_Master(currency_id)
);
CREATE TABLE StreemLyne_MT.Stage_Master (
  stage_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  stage_name character varying NOT NULL UNIQUE,
  stage_description character varying,
  preceding_stage_id smallint,
  stage_type smallint NOT NULL,
  CONSTRAINT Stage_Master_pkey PRIMARY KEY (stage_id)
);
CREATE TABLE StreemLyne_MT.Subscription_Module_Mapping (
  subscription_module_mapping_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  subscription_id bigint NOT NULL,
  module_id bigint NOT NULL,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT Subscription_Module_Mapping_pkey PRIMARY KEY (subscription_module_mapping_id),
  CONSTRAINT Subscription_Module_Mapping_module_id_fkey FOREIGN KEY (module_id) REFERENCES StreemLyne_MT.Module_Master(module_id),
  CONSTRAINT Subscription_Module_Mapping_subscription_id_fkey FOREIGN KEY (subscription_id) REFERENCES StreemLyne_MT.Subscription_Plans(subscription_id)
);
CREATE TABLE StreemLyne_MT.Subscription_Plans (
  subscription_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  subscription_code character varying NOT NULL UNIQUE,
  subscription_name character varying NOT NULL UNIQUE,
  description character varying,
  is_base_plan boolean NOT NULL,
  is_active boolean NOT NULL,
  billing_cycle smallint NOT NULL,
  price numeric NOT NULL,
  currency_id smallint NOT NULL,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone,
  CONSTRAINT Subscription_Plans_pkey PRIMARY KEY (subscription_id),
  CONSTRAINT Subscription_Plans_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES StreemLyne_MT.Currency_Master(currency_id)
);
CREATE TABLE StreemLyne_MT.Supplier_Master (
  supplier_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  supplier_company_name character varying NOT NULL,
  supplier_contact_name character varying,
  supplier_provisions smallint,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT Supplier_Master_pkey PRIMARY KEY (supplier_id)
);
CREATE TABLE StreemLyne_MT.Tenant_Master (
  tenant_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  tenant_company_name character varying UNIQUE,
  tenant_contact_name character varying,
  onboarding_Date date,
  is_active boolean,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone,
  CONSTRAINT Tenant_Master_pkey PRIMARY KEY (tenant_id)
);
CREATE TABLE StreemLyne_MT.Tenant_Module_Mapping (
  tenant_module_mapping_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  tenant_id smallint,
  module_id smallint,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT Tenant_Module_Mapping_pkey PRIMARY KEY (tenant_module_mapping_id),
  CONSTRAINT Tenant_Module_Mapping_module_id_fkey FOREIGN KEY (module_id) REFERENCES StreemLyne_MT.Module_Master(module_id),
  CONSTRAINT Tenant_Module_Mapping_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES StreemLyne_MT.Tenant_Master(tenant_id)
);
CREATE TABLE StreemLyne_MT.Tenant_Subscription (
  tenant_subscription_mapping_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  tenant_id bigint,
  subscription_id bigint,
  subscription_start_date date,
  subscription_end_date date,
  is_active boolean,
  auto_renew boolean,
  created_at timestamp without time zone NOT NULL,
  updated_at timestamp without time zone,
  CONSTRAINT Tenant_Subscription_pkey PRIMARY KEY (tenant_subscription_mapping_id),
  CONSTRAINT Tenant_Subscription_subscription_id_fkey FOREIGN KEY (subscription_id) REFERENCES StreemLyne_MT.Subscription_Plans(subscription_id),
  CONSTRAINT Tenant_Subscription_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES StreemLyne_MT.Tenant_Master(tenant_id)
);
CREATE TABLE StreemLyne_MT.UOM_Master (
  uom_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  uom_description character varying NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT UOM_Master_pkey PRIMARY KEY (uom_id)
);
CREATE TABLE StreemLyne_MT.User_Master (
  user_id smallint GENERATED ALWAYS AS IDENTITY NOT NULL UNIQUE,
  employee_id smallint,
  user_name character varying UNIQUE,
  password character varying,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at date,
  CONSTRAINT User_Master_pkey PRIMARY KEY (user_id),
  CONSTRAINT User_Master_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES StreemLyne_MT.Employee_Master(employee_id)
);
CREATE TABLE StreemLyne_MT.User_Role_Mapping (
  user_id integer NOT NULL,
  role_id integer NOT NULL,
  CONSTRAINT User_Role_Mapping_pkey PRIMARY KEY (user_id, role_id)
);