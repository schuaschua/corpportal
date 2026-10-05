import {
  Button,
  Dropdown,
  Field,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useState } from 'react';
import { DEMO_USERS, useAuth } from '../auth/AuthContext';
import { Logo, SyntheticBanner } from '../components/Shell';
import { useShared } from '../components/styles';

const useStyles = makeStyles({
  page: { minHeight: '100vh', backgroundColor: tokens.colorNeutralBackground2 },
  center: { display: 'grid', placeItems: 'center', minHeight: 'calc(100vh - 24px)' },
  card: { width: '380px', padding: '32px', display: 'flex', flexDirection: 'column', gap: '12px' },
  title: { fontSize: tokens.fontSizeBase500, lineHeight: tokens.lineHeightBase500, fontWeight: tokens.fontWeightSemibold, margin: '12px 0 0' },
  ms: { display: 'flex', gap: '2px', flexWrap: 'wrap', width: '22px' },
  sq: { width: '10px', height: '10px', display: 'block' },
});

function MicrosoftMark() {
  const s = useStyles();
  return (
    <span className={s.ms} aria-hidden>
      {['#F25022', '#7FBA00', '#00A4EF', '#FFB900'].map((c) => (
        <i key={c} className={s.sq} style={{ background: c }} />
      ))}
    </span>
  );
}

export function Login() {
  const s = useStyles();
  const shared = useShared();
  const auth = useAuth();
  const [demoUser, setDemoUser] = useState(DEMO_USERS[0].username);
  const busy = auth.status === 'loading';

  return (
    <div className={s.page}>
      <SyntheticBanner />
      <div className={s.center}>
        <div className={`${shared.card} ${s.card}`}>
          <Logo />
          <h1 className={s.title}>Corporate banking</h1>
          <p className={shared.sub} style={{ margin: 0 }}>Sign in with your company account.</p>
          {auth.error && (
            <MessageBar intent="error">
              <MessageBarBody>{auth.error}</MessageBarBody>
            </MessageBar>
          )}
          {auth.mode === 'dev' && (
            <Field label="Demo user (local sign-in, PoC only)">
              <Dropdown
                value={DEMO_USERS.find((u) => u.username === demoUser)?.name}
                selectedOptions={[demoUser]}
                onOptionSelect={(_, d) => d.optionValue && setDemoUser(d.optionValue)}
              >
                {DEMO_USERS.map((u) => (
                  <Option key={u.username} value={u.username}>{u.name}</Option>
                ))}
              </Dropdown>
            </Field>
          )}
          <Button
            appearance="primary"
            size="large"
            disabled={busy}
            icon={busy ? <Spinner size="tiny" /> : <MicrosoftMark />}
            onClick={() => auth.signIn(demoUser)}
          >
            Sign in with Microsoft
          </Button>
          <p className={shared.tip}>Access is limited to your company's accounts. Every sign-in is logged.</p>
        </div>
      </div>
    </div>
  );
}
