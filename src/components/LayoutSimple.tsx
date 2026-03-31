import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

interface LayoutSimpleProps {
  title: string;
  description?: string;
  children: ReactNode;
  backTo?: string;
  backLabel?: string;
  footer?: ReactNode;
}

export function LayoutSimple({
  title,
  description,
  children,
  backTo,
  backLabel,
  footer,
}: LayoutSimpleProps) {
  return (
    <div className="page-shell">
      <header className="panel page-header">
        <div>
          <p className="eyebrow">AccessibleCourse</p>
          <h1>{title}</h1>
          {description ? <p>{description}</p> : null}
        </div>
        {backTo && backLabel ? (
          <Link className="secondary-button" to={backTo}>
            {backLabel}
          </Link>
        ) : null}
      </header>

      <main>{children}</main>
      {footer ? <div>{footer}</div> : null}
    </div>
  );
}
