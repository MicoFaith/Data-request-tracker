import React from "react";
import { api } from "./api";
import { Form, Field, roleOptions } from "./ui";

export function UserProfile({ person, isSelf, onChange }) {
  return (
    <div className="profile-controls">
      <Form
        className="profile-edit"
        label="Save profile"
        submit={async (values) => {
          await api(`users/${person.id}/`, {
            method: "PATCH",
            body: {
              name: values.name,
              email: values.email,
              organisation: values.organisation,
              ...(!isSelf
                ? { role: values.role, is_active: values.active === "true" }
                : {}),
            },
          });
          await onChange("Profile updated.");
        }}
      >
        {(errors) => (
          <>
            <Field
              label={`Full name for ${person.email}`}
              name="name"
              defaultValue={person.name}
              required
              maxLength={120}
              error={errors.name}
            />
            <Field
              label={`Email for ${person.name}`}
              name="email"
              type="email"
              defaultValue={person.email}
              required
              maxLength={150}
              error={errors.email}
              help="Changing this updates the sign-in email immediately and turns off email alerts until the user opts in again. The password stays the same."
            />
            <Field
              label={`Organisation for ${person.name}`}
              name="organisation"
              defaultValue={person.organisation || ""}
              maxLength={120}
              error={errors.organisation}
              help="Optional"
            />
            {!isSelf && (
              <>
                <Field label="Role" name="role" error={errors.role}>
                  <select defaultValue={person.role}>
                    {roleOptions.slice(1).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="Account status"
                  name="active"
                  error={errors.is_active}
                >
                  <select defaultValue={String(person.is_active)}>
                    <option value="true">Active</option>
                    <option value="false">Inactive</option>
                  </select>
                </Field>
              </>
            )}
          </>
        )}
      </Form>
      {!isSelf && (
        <details className="delete-account">
          <summary>Delete account</summary>
          <p>
            Deletion is permanent. Accounts linked to requests or audit history
            must be deactivated instead.
          </p>
          <Form
            className="delete-form"
            label="Permanently delete account"
            submit={async (values) => {
              await api(`users/${person.id}/`, {
                method: "DELETE",
                body: { confirm_email: values.confirm_email },
              });
              await onChange(`Account ${person.email} deleted.`);
            }}
          >
            {(errors) => (
              <Field
                name="confirm_email"
                label={`Type ${person.email} to confirm`}
                type="email"
                required
                autoComplete="off"
                error={errors.confirm_email}
              />
            )}
          </Form>
        </details>
      )}
    </div>
  );
}
